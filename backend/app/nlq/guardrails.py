"""Validation and sandboxed execution for LLM-generated SQL.

The threat model here is not a malicious user typing SQL -- users only ever
send English. It is that the model can be *talked into* emitting whatever the
question implies, including `DROP TABLE users` or a `SELECT password_hash`.
So the generated SQL is treated as untrusted input and has to clear four
independent gates before it runs:

1. **Shape** -- exactly one statement, starting with SELECT or WITH.
2. **Keyword deny-list** -- no DDL/DML, no PRAGMA/ATTACH, no SQLite file
   functions, checked on whole words outside string literals.
3. **Table allow-list** -- every table referenced must be one of the analytics
   tables. ``users`` is not on that list, so account data is unreachable by
   construction.
4. **Read-only connection** -- the query executes over a *separate* SQLite
   handle opened with ``mode=ro``, with a row cap and a wall-clock interrupt.
   Even a bypass of gates 1-3 cannot write.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

ALLOWED_TABLES = {"games", "plays", "teams", "player_box"}

# Note: `replace` is deliberately absent -- it is a legitimate SQLite string
# function, and `REPLACE INTO` is already unreachable because a statement must
# begin with SELECT or WITH and only one statement is permitted.
DENIED_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "grant", "revoke", "attach", "detach", "pragma", "vacuum",
    "reindex", "commit", "rollback", "savepoint",
    "load_extension", "readfile", "writefile", "fts3_tokenizer",
}

# `INTO` catches `SELECT ... INTO outfile` style exfiltration on engines that
# support it.
DENIED_PHRASES = [
    re.compile(r"\binto\s+(outfile|dumpfile)\b", re.I),
    re.compile(r"\bselect\b[^;]*\binto\b\s+\w+", re.I),
]

_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([`\"\[]?)([A-Za-z_][A-Za-z0-9_]*)\1", re.I)
_CTE_NAME = re.compile(r"\b(?:with|,)\s+([A-Za-z_][A-Za-z0-9_]*)\s+as\s*\(", re.I)
_LIMIT = re.compile(r"\blimit\b\s+\d+", re.I)


class SQLGuardrailError(ValueError):
    """Raised when generated SQL fails validation. Never leaks the raw SQL."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool


def _strip_noise(sql: str) -> str:
    """Remove comments and string literals so keyword scanning sees only code."""
    s = _COMMENT_BLOCK.sub(" ", sql)
    s = _COMMENT_LINE.sub(" ", s)
    s = _STRING_LITERAL.sub("''", s)
    return s


def normalize(sql: str) -> str:
    sql = _COMMENT_BLOCK.sub(" ", sql)
    sql = _COMMENT_LINE.sub(" ", sql)
    sql = sql.strip()
    # Models like to wrap output in markdown fences.
    sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.I).strip()
    return sql.rstrip(";").strip()


def validate(sql: str, row_limit: int = 500) -> str:
    """Validate and return SQL with an enforced LIMIT. Raises on rejection."""
    statement = normalize(sql)
    if not statement:
        raise SQLGuardrailError("Empty query.")

    scan = _strip_noise(statement)

    if ";" in scan:
        raise SQLGuardrailError("Only a single statement is allowed.")

    if not re.match(r"^\s*(select|with)\b", scan, re.I):
        raise SQLGuardrailError("Only SELECT queries are allowed.")

    words = set(w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", scan))
    hit = words & DENIED_KEYWORDS
    if hit:
        raise SQLGuardrailError(
            f"Query uses a disallowed keyword: {sorted(hit)[0].upper()}."
        )

    for pattern in DENIED_PHRASES:
        if pattern.search(scan):
            raise SQLGuardrailError("Query uses a disallowed construct.")

    cte_names = {m.group(1).lower() for m in _CTE_NAME.finditer(scan)}
    referenced = {m.group(2).lower() for m in _TABLE_REF.finditer(scan)}
    unknown = referenced - ALLOWED_TABLES - cte_names
    if unknown:
        raise SQLGuardrailError(
            f"Query references a table that is not queryable: {sorted(unknown)[0]}."
        )
    if not referenced:
        raise SQLGuardrailError("Query does not reference any known table.")

    if not _LIMIT.search(scan):
        statement = f"{statement}\nLIMIT {row_limit}"
    return statement


def _readonly_uri(database_url: str) -> str:
    if not database_url.startswith("sqlite"):
        raise SQLGuardrailError(
            "The sandboxed query runner currently supports SQLite only. "
            "For Postgres, point it at a role with SELECT-only grants."
        )
    path = database_url.split("///", 1)[-1]
    return f"file:{Path(path).as_posix()}?mode=ro"


def execute_readonly(
    sql: str,
    database_url: str,
    row_limit: int = 500,
    timeout_seconds: float = 20.0,
) -> QueryResult:
    """Run validated SQL over a read-only handle with a hard time cap."""
    uri = _readonly_uri(database_url)
    conn = sqlite3.connect(uri, uri=True, timeout=timeout_seconds)
    timer = threading.Timer(timeout_seconds, conn.interrupt)
    timer.daemon = True
    timer.start()
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(row_limit + 1)
        truncated = len(rows) > row_limit
        rows = rows[:row_limit]
        return QueryResult(
            columns=columns, rows=[list(r) for r in rows], truncated=truncated
        )
    except sqlite3.OperationalError as exc:
        raise SQLGuardrailError(f"Query could not run: {exc}") from None
    finally:
        timer.cancel()
        conn.close()

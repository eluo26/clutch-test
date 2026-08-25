"""Natural-language query endpoint (text-to-SQL)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.deps import nlq_rate_limit
from app.models import User
from app.nlq import guardrails
from app.nlq.provider import get_provider
from app.nlq.schema_context import SCHEMA_DOC
from app.schemas import NLQRequest, NLQResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nlq", tags=["nlq"])


@router.get("/schema")
def schema(_: User = Depends(nlq_rate_limit)):
    """What the model is told about the database -- exposed so the UI can
    show users which tables and conventions are actually queryable."""
    return {
        "tables": sorted(guardrails.ALLOWED_TABLES),
        "schema_doc": SCHEMA_DOC,
    }


@router.post("/query", response_model=NLQResponse)
def query(payload: NLQRequest, user: User = Depends(nlq_rate_limit)):
    settings = get_settings()
    provider = get_provider()

    try:
        raw_sql = provider.generate(payload.question)
    except Exception as exc:  # noqa: BLE001
        log.exception("text-to-SQL generation failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not generate a query: {type(exc).__name__}",
        ) from None

    try:
        sql = guardrails.validate(raw_sql, settings.nlq_row_limit)
    except guardrails.SQLGuardrailError as exc:
        # Log the rejected SQL for review; return only the reason.
        log.warning("rejected SQL from %s (user %s): %s", provider.name, user.id, raw_sql)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    try:
        result = guardrails.execute_readonly(
            sql,
            settings.database_url,
            row_limit=settings.nlq_row_limit,
            timeout_seconds=settings.nlq_timeout_seconds,
        )
    except guardrails.SQLGuardrailError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    explanation = None
    if payload.explain:
        try:
            explanation = provider.explain(
                payload.question, sql, result.columns, result.rows
            )
        except Exception:  # noqa: BLE001 - explanation is a nicety, not the answer
            log.debug("explanation step failed", exc_info=True)

    return NLQResponse(
        question=payload.question,
        sql=sql,
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        provider=provider.name,
        explanation=explanation,
    )

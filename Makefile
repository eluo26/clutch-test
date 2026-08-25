.PHONY: help install seed api web sim test lint backtest fixtures ingest clean

help:
	@echo "Clutch — NBA analytics platform"
	@echo
	@echo "  make install    install backend + frontend dependencies"
	@echo "  make seed       load the bundled sample data into SQLite"
	@echo "  make api        run the FastAPI backend on :8000"
	@echo "  make web        run the React dev server on :5173"
	@echo "  make sim        run the Java simulation service on :8081 (optional)"
	@echo "  make test       run the Python test suite"
	@echo "  make lint       ruff check the backend"
	@echo "  make backtest   print a calibration backtest to the terminal"
	@echo "  make fixtures   regenerate the bundled sample fixtures"
	@echo "  make ingest     pull real games (SEASON=2023-24 LIMIT=25)"
	@echo
	@echo "First run:  make install && make seed && make api   (then 'make web')"

install:
	cd backend && python -m pip install -e '.[dev,llm]'
	cd frontend && npm install

seed:
	cd backend && python -m app.ingest.cli seed

api:
	cd backend && python -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

sim:
	cd java-sim && mvn spring-boot:run

test:
	cd backend && python -m pytest

lint:
	cd backend && ruff check app tests

backtest:
	cd backend && python -m app.ingest.cli backtest --model blend

fixtures:
	cd backend && python scripts/make_fixtures.py

SEASON ?= 2023-24
LIMIT ?= 25
ingest:
	cd backend && python -m pip install -e '.[ingest]' \
		&& python -m app.ingest.cli nba --season $(SEASON) --limit $(LIMIT)

clean:
	rm -f backend/clutch.db backend/clutch.db-wal backend/clutch.db-shm
	rm -rf frontend/dist java-sim/target
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Format and lint all maintained Python source, including offline test helpers.
lint:
    uv run ruff format --check docs src tests tests_postgres scripts examples/fastapi_server/app examples/fastapi_server/alembic
    uv run ruff check src tests tests_postgres scripts examples/fastapi_server/app examples/fastapi_server/alembic

format:
    uv run ruff format docs src tests tests_postgres scripts examples/fastapi_server/app examples/fastapi_server/alembic

# No external network/services/credentials are used by the default suite.
test:
    uv run pytest --cov=notify_kit --cov-report=term-missing --cov-report=xml --cov-fail-under=90

typecheck:
    uv run basedpyright --level error

# Only invoke against a disposable cluster; creates/drops temporary databases.
test-postgres:
    uv run --extra postgres pytest tests_postgres

package:
    uv build --offline --no-build-isolation
    uv run twine check --strict dist/*
    uv run python scripts/check_distribution.py

check: lint typecheck test package

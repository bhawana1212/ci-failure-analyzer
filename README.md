# CI Failure Analyzer

A small CI observability application that turns Jenkins-style console logs into structured build analysis. Built with Python, FastAPI, SQLAlchemy, SQLite/PostgreSQL and a responsive HTML/CSS/JavaScript dashboard.

## Features

- Upload UTF-8 logs or paste console output (up to 2 MiB).
- Classify build failures, test failures, compilation errors, timeouts and infrastructure errors.
- Extract failed test identifiers from common pytest, unittest, Google Test and Maven/Surefire output.
- Identify Jenkins stages and show matching evidence with source line numbers.
- Track passed, failed, unstable, aborted and unknown outcomes.
- View pass rate, recent builds, category breakdown and frequently failing tests.
- Search build metadata, filter results, paginate, inspect details and export analysis as JSON.
- Delete analyses with confirmation; associated test records are removed too.
- Use SQLite locally or PostgreSQL with Docker Compose.
- Query and ingest results through REST APIs with interactive OpenAPI documentation.
- Load 12 explicitly synthetic sample builds from the empty dashboard.

Summaries are deterministic and rule-based. No AI service, API key or external log processing is required.

## Quick Start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from the project directory:

```sh
uv sync --frozen --extra dev --python 3.12
uv run uvicorn ci_analyzer.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Select **Load sample builds** for a demo, or analyze [examples/jenkins-failure.log](examples/jenkins-failure.log).

- Interactive API docs: http://127.0.0.1:8000/docs
- Database health: http://127.0.0.1:8000/health
- Local database: `ci-analyzer.db` in the working directory, created at startup and ignored by Git.

Python 3.11+ is required; uv can install Python automatically. On corporate networks with a trusted system certificate store, use `uv --native-tls sync --frozen --extra dev` if certificate verification fails. Do not disable TLS verification.

Without uv, install the package into a Python virtual environment with `pip install -e ".[dev]"`, then run `python -m uvicorn ci_analyzer.main:app --host 127.0.0.1 --port 8000`. This resolves the dependency ranges rather than the exact versions in `uv.lock`.

## Docker and PostgreSQL

Requires Docker with Compose. Create a local `.env` using `.env.example` and set `POSTGRES_PASSWORD` to a random, URL-safe alphanumeric password. Never commit `.env`.

```sh
docker compose up --build -d
docker compose logs -f app
```

Open **http://127.0.0.1:8000**. PostgreSQL uses a persistent named volume and is not exposed on the host. The app waits for the database health check and runs as a non-root user. Stop with `docker compose down`; the data volume is retained.

For standalone SQLite in Docker:

```sh
docker build -t ci-failure-analyzer .
docker run --rm -p 127.0.0.1:8000:8000 -v ci-analyzer-data:/data ci-failure-analyzer
```

To connect to an existing PostgreSQL database, set `DATABASE_URL` before starting the server:

```text
postgresql+psycopg://USER:URL_ENCODED_PASSWORD@HOST:5432/DATABASE
```

Tables are created at startup. This initial version does not implement schema migrations; add Alembic before evolving a deployed database.

## REST API

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/builds` | Analyze a JSON log payload and persist the result |
| POST | `/api/builds/upload` | Analyze a multipart text file |
| GET | `/api/builds` | List builds with `status`, `category`, `project`, `search`, `limit`, `offset` |
| GET | `/api/builds/{id}` | Get analysis, failed tests and evidence |
| DELETE | `/api/builds/{id}` | Delete a build and its test records |
| GET | `/api/metrics` | Aggregate statuses, categories and frequently failing tests |
| GET | `/health` | Check application and database connectivity |

Example JSON body for `POST /api/builds`:

```json
{
  "name": "Build #142",
  "project": "firmware-ci",
  "branch": "main",
  "log": "[Pipeline] { (unit-tests)\nFAILED tests/test_boot.py::test_boot_sequence - AssertionError\n[Pipeline] }\nFinished: FAILURE"
}
```

Example response fields:

```json
{
  "status": "failed",
  "category": "test",
  "failed_stage": "unit-tests",
  "failed_tests": ["tests/test_boot.py::test_boot_sequence"],
  "summary": "A test failure was detected. Inspect its assertion or setup error."
}
```

Upload from a terminal (use `curl.exe` in Windows PowerShell):

```sh
curl -X POST http://127.0.0.1:8000/api/builds/upload -F "name=Build #142" -F "project=firmware-ci" -F "branch=main" -F "file=@examples/jenkins-failure.log"
```

API ingestion creates a new record each time; it does not deduplicate retries or build names. Timestamps represent ingestion time, not the original CI build time.

## How Analysis Works

1. Validate input size, remove ANSI colors and redact common credential patterns.
2. Scan lines for Jenkins stage markers, terminal status, test names and failure signatures.
3. Use the **last** `Finished: SUCCESS/FAILURE/UNSTABLE/ABORTED` marker when present. A final success takes precedence over recovered errors and produces no failed-test records.
4. When failure signatures overlap, choose a primary category in this order: timeout, infrastructure, compilation, test, build. Keep evidence for all matching categories.
5. Attribute the failed stage to the first evidence line in the primary category. Store up to 8 evidence lines per category, 600 characters per line, and 500 unique test names.

An incomplete log without a terminal marker or recognized failure stays **unknown**, never automatically passed. A log with a recognized failure but no terminal marker is inferred to have failed. The evidence is a diagnostic hint, not proof of root cause. Parallel/interleaved Jenkins stages, custom log prefixes, non-Jenkins success markers and unfamiliar test formats can require additional rules.

Metrics cover **all stored builds**, independently of the history filters. Pass rate is passed builds divided by all non-unknown outcomes, including failed, unstable and aborted. The category chart includes all non-passing builds, including unknowns. Frequent-test counts are the number of distinct stored builds containing each test, not the number of repeated log lines. They do not prove test flakiness.

## Security and Privacy

This is a **local/trusted-environment portfolio application**, not a hardened public service.

- No authentication, authorization, rate limiting or tenancy is provided. Bind to loopback as documented. Put authentication, TLS, request-size limits and access controls in front of it before network exposure.
- Raw logs are not persisted. Build metadata, test names, bounded evidence and summaries are stored.
- Redaction recognizes common password/token assignments, authorization schemes, URL credentials and GitHub token prefixes. It is **not a complete secret scanner**. Remove secrets and proprietary content before ingestion; extracted names and evidence may still be sensitive.
- API bodies are parsed before application-level validation. Enforce an HTTP body limit at a reverse proxy for network deployments.
- The dashboard renders log content as escaped text. Google Fonts and the pinned Lucide CDN supply fonts and icons; no log content is sent to these services. The core dashboard still works when these assets are unavailable.
- Only synthetic examples belong in this public repository. Local databases, environments and credentials are ignored by Git.

## Tests and CI

```sh
uv sync --frozen --extra dev
uv run pytest -q
uv run ruff check .
```

Tests cover classification, runner formats, stages, redaction, successful retries, unknown outcomes, input limits, REST ingestion, filtering, pagination, metrics, persistence, deletion and sample assets. The PostgreSQL integration test is skipped unless `TEST_DATABASE_URL` points to a dedicated test database.

GitHub Actions is configured for Python 3.11/3.12/3.13, SQLite tests, lint, a PostgreSQL 16 integration test, and a Docker build/health smoke test. These are configuration targets, not a claim that CI has already passed.

## Project Layout

```text
ci_analyzer/
  analyzer.py          Log parsing and rule-based classification
  database.py          SQLAlchemy tables and database engine
  main.py              REST API, metrics and static asset serving
  static/              Dashboard and synthetic sample data
tests/                 Parser, API and PostgreSQL tests
examples/              Synthetic Jenkins console log
.github/workflows/     Automated checks
Dockerfile             Non-root application container
compose.yaml           Application and PostgreSQL
uv.lock                Reproducible Python dependencies
```

## Possible Next Steps

JUnit XML ingestion, authenticated Jenkins webhooks, build-duration trends, schema migrations and optional privacy-aware AI summaries are intentionally outside this first version.
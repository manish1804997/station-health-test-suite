# Station Health API — Test Automation Suite

A layered pytest suite, quality strategy, and CI pipeline for the NOC
station-health microservice in [`service/`](service/).

- **[TEST_STRATEGY.md](TEST_STRATEGY.md)** — the test approach, tool choices,
  test data strategy, CI/CD design, assumptions, and gaps. Start here.
- **[AI_USAGE.md](AI_USAGE.md)** — how AI tooling was used to build this suite.
- **[.github/workflows/ci.yml](.github/workflows/ci.yml)** — the CI pipeline.

## Repo layout

```
service/            The microservice under test (unmodified)
clients/
  http_client_handler.py  Thin HTTP client (one method per endpoint), used by tests/e2e
builder/
  factories.py       Shared test data builder
config/
  config.py           E2E target URL, overridable via E2E_BASE_URL env var
conftest.py          DB-isolated TestClient fixture, shared by unit/api/perf
tests/
  unit/               Pure-function tests for the scoring formula, no I/O
  api/                Integration tests against every endpoint (SQLite)
  perf/               Concurrency correctness smoke test
  e2e/                Smoke tests against the real docker-compose stack (Postgres)
requirements-test.txt  Test-only dependencies
pyproject.toml          pytest config (markers, pythonpath)
ruff.toml               Lint config (scoped to test code only)
```

## Setup

### 1. Start the service

```bash
# Docker (recommended) — runs the API against real Postgres
cd service && docker compose up -d

# or locally, against SQLite
cd service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

> Note: `psycopg2-binary` needs a prebuilt wheel for your Python version. If
> `pip install -r service/requirements.txt` fails to build it locally (e.g.
> on a very new Python release), you don't need it at all for `tests/unit`,
> `tests/api`, or `tests/perf` — those run entirely against SQLite. Install
> everything except `psycopg2-binary` in that case; it's only needed to run
> the service itself against Postgres, which the `tests/e2e` job does inside
> Docker where the wheel is available.

### 2. Install test dependencies

From the repo root (a separate virtualenv from the service's is fine, or
reuse `service/.venv`):

```bash
pip install -r service/requirements.txt   # or the subset above, minus psycopg2-binary
pip install -r requirements-test.txt
```

## Running the tests

All commands run from the repo root.

```bash
# Fast suite: unit + API + concurrency smoke — no external services needed
pytest tests/unit tests/api tests/perf

# With coverage
pytest tests/unit tests/api tests/perf --cov=service/app --cov-report=term-missing

# Just the scoring-formula unit tests
pytest tests/unit -v

# E2E smoke tests — requires `docker compose up` from service/ first
pytest tests/e2e -m e2e -v

# Everything (e2e tests auto-skip if the docker stack isn't running)
pytest tests -v

# With a self-contained HTML report you can open in a browser
pytest tests/unit tests/api tests/perf --html=reports/report.html --self-contained-html
```

All generated reports (coverage, JUnit XML, HTML) go into `reports/`,
which is gitignored — it's regenerated on every run, not source.

Test markers (`unit`, `api`, `perf`, `e2e`) are registered in
`pyproject.toml` and can be combined, e.g. `pytest -m "unit or api"`.

## CI

Every pull request and push to `main` runs, in order: lint (`ruff` on
`tests/`) → unit + API + concurrency tests against SQLite → E2E smoke tests
against a real `docker compose` Postgres stack. See
[TEST_STRATEGY.md §4](TEST_STRATEGY.md#4-cicd-integration) for the full
rationale.

Each run uploads a self-contained HTML report (`pytest-html`) as a build
artifact — `html-report` for the unit/API/perf job, `html-report-e2e` for
the e2e job — alongside the existing `coverage-xml` and `junit-results`
artifacts. Download it from the workflow run's Summary page and open it
in a browser for a readable pass/fail/skip breakdown with failure output.

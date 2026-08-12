# Test Strategy — NOC Station Health API

**Contents:** [1. Approach](#1-approach) · [2. Tool choices](#2-tool-choices) ·
[3. Test data strategy](#3-test-data-strategy) ·
[4. CI/CD integration](#4-cicd-integration) ·
[5. Gaps & future work](#5-gaps--future-work)

---

## 1. Approach

I started by reading the service rather than assuming its shape. It's
small, and once you look at it, the risk is concentrated in three places:

- a pure scoring formula (`app/scoring.py`)
- a handful of SQL queries that compute "latest report per station" via a
  `MAX(timestamp)` subquery + join (`app/routers/*.py`)
- the request/response contracts at the HTTP boundary (pydantic schemas)

There's no auth, no background jobs, no external service calls, and the
"UI" is a single static HTML page with no client-side logic worth testing.
Given that shape, a classic 70/20/10 unit pyramid just doesn't fit —
almost all of the actual risk lives at the integration boundary, not
inside pure functions. So the suite ended up closer to a **trophy** than a
pyramid:

| Layer | Location | What it covers | Why this weight |
|---|---|---|---|
| Unit | `tests/unit/` | `scoring.py`: penalty math, caps, rounding, the flagging boundary | Small and cheap, but this is the *only* place with real branching logic worth isolating. 16 tests. |
| API / integration | `tests/api/` | Every endpoint, through real FastAPI routing + pydantic validation + SQLAlchemy against an isolated SQLite DB | The workhorse layer — the only one that can see SQL join/subquery bugs, validation edge cases, and cross-endpoint consistency (e.g. does `/metrics/summary` agree with `/stations`?). 37 tests. |
| Concurrency smoke | `tests/perf/` | Light concurrent writes don't get lost or corrupt aggregates | A correctness check, not a load test (see [§5](#5-gaps--future-work)). 1 test. |
| E2E | `tests/e2e/` | The real docker-compose stack: Postgres, psycopg2, the actual ASGI server, `SIMULATED_LATENCY_MS=40` | The SQLite/TestClient layer can't exercise the Postgres-specific code path at all — different driver, different transaction/locking semantics, real network hop. 4 tests. |

A few things I looked at and decided weren't worth building:

- **A full load/performance harness.** The assignment explicitly scopes
  this out, and honestly it belongs against the Postgres stack, not
  SQLite (see [§5](#5-gaps--future-work) for why those two environments
  aren't interchangeable for perf work). I wrote up the correct approach
  in the perf test's docstring instead of half-building something that
  wouldn't hold up anyway.
- **UI/browser tests.** `/` serves a static, read-only dashboard with no
  interactive logic. A Playwright suite for a page that renders JSON into
  a table would cost more to maintain than it would ever catch.
- **Auth/authz tests.** There is no auth on any endpoint. Nothing to test.
- **Mocked-DB unit tests for the routers.** I actually started down this
  path, then backed out of it — the bug I found (below) lives *in* the SQL
  join logic, and mocking the DB would have hidden exactly the class of
  defect this service most needs covered. See `AI_USAGE.md` Example 3 for
  how that decision came about.
- **Property-based/fuzz testing of the scoring formula.**
  `compute_hygiene_score` has exactly two caps and one flat penalty.
  Parametrized boundary cases give you the same confidence Hypothesis
  would here, without the added dependency and mental overhead. I'd
  revisit this if the formula grows more branches.

### A real defect the suite documents

While poking around the service before writing any tests, I noticed that
`list_stations()` and `get_metrics_summary()` both determine "the latest
report per station" by joining on `StationReport.timestamp ==
MAX(timestamp)`. If two reports for the same station happen to share an
**identical** timestamp, that equality join matches *both* rows — the
station shows up twice in `/stations` with conflicting data (e.g.
simultaneously "online" and "offline"), and gets double-counted in
`/metrics/summary`.

I captured it as two `xfail(strict=True)` tests (`tests/api/test_stations.py`,
`tests/api/test_metrics.py`), with the root cause and the fix direction
written right into the failure reason, rather than quietly asserting the
buggy behavior or just leaving it undiscovered. `strict=True` means these
tests will loudly `XPASS`-fail CI the moment someone fixes the query —
that's the cue to delete the `xfail` marker and let them become normal
regression tests.

---

## 2. Tool choices

Nothing exotic here — mostly boring choices for boring reasons:

- **pytest** — the standard for Python test suites; fixtures + parametrize +
  markers cover everything this suite needs without reaching for something
  heavier.
- **FastAPI's `TestClient` (httpx-based)** for the unit/API/perf layers —
  in-process, no real socket, and it exercises the *actual* ASGI routing,
  pydantic validation, and SQLAlchemy layer rather than a hand-rolled call
  into route functions. Dependency injection (`app.dependency_overrides`)
  swaps in an isolated DB per test — the FastAPI-native way to do this,
  rather than monkeypatching internals.
- **SQLAlchemy + a fresh SQLite file per test** for the API layer — this is
  why the bulk of the suite runs in well under a second with zero external
  services (`pytest tests/unit tests/api tests/perf` needs nothing but a
  Python environment). SQLite isn't a stand-in for Postgres correctness at
  the SQL-dialect level, but every query this service runs (subqueries,
  joins, aggregates) is portable ANSI SQL, so it's a valid substrate for
  logic tests. The e2e layer exists precisely to cover what this can't
  ([§5](#5-gaps--future-work)).
- **Raw `httpx`** (not `TestClient`) for the e2e layer — these tests talk
  to an already-running server over real HTTP, the only way to actually
  exercise the docker-compose stack.
  - I wrapped the raw calls in `clients/http_client_handler.py`
    (`StationHealthClient`, one method per endpoint) so the test bodies
    read as intent rather than repeated
    `httpx.post(f"{base_url}/reports", ...)` boilerplate — same reasoning
    as the `builder/factories.py` payload builder below, just applied to
    the one layer that makes real network calls.
  - The target URL lives in `config/config.py`, overridable via
    `E2E_BASE_URL`, so the suite can point at a stack other than the
    default `localhost:8000` without touching test code.
- **ruff** — one fast linter/import-sorter instead of a Black+isort+flake8
  stack, scoped to this suite's own code (`tests/`, `clients/`, `builder/`,
  `config/`, `conftest.py`). I didn't lint `service/` — that's the
  platform team's code, and it's not this suite's call to gate CI on their
  style choices.
- **pytest-cov** — coverage gets reported (currently 97% line coverage
  across `app/`) as a signal in CI artifacts, not enforced as a hard gate.
  A percentage threshold on a suite this size mostly just invites tests
  written to move the number rather than catch regressions; I'd rather
  lean on code review judgment while the suite is small, and revisit a
  gate (e.g. "no PR may lower coverage") once it's big enough that
  regressions stop being visible by eye.
- **pytest-html** — a self-contained HTML report
  (`--html=reports/report.html --self-contained-html`) uploaded as a CI
  artifact alongside `junit.xml` and `coverage.xml` (all three land in one
  `reports/` folder, gitignored since they're regenerated every run).
  `junit.xml` is for machines — CI dashboards, historical trend tools —
  this one's for a human to open in a browser and get a readable
  pass/fail/skip breakdown with failure tracebacks, no JUnit viewer or
  local rerun required.

I didn't reach for a mocking library anywhere — there's nothing in this
service worth mocking. The one external dependency (Postgres, in Docker)
gets tested for real in the e2e layer instead of being faked.

---

## 3. Test data strategy

- **One factory, `builder/factories.py::report_payload(**overrides)`.**
  Every test that needs a report payload calls this and overrides only the
  fields it actually cares about. Keeps tests readable — the override list
  *is* the test's intent — and means a schema change to `ReportIn` touches
  exactly one function, not dozens of inline dicts scattered everywhere.
- **Per-test isolation via a fresh SQLite file + dependency override**
  (`conftest.py::client`, sitting at the repo root rather than under
  `tests/` since it's shared support code, not a test itself). Each test
  gets its own DB file under pytest's `tmp_path` and its own
  `sessionmaker`, injected through `app.dependency_overrides[get_db]`. No
  test can see another test's rows, there are no ordering dependencies,
  and the suite is already safe to parallelize with `pytest-xdist` even
  though that isn't wired up yet (see [§5](#5-gaps--future-work)).
- **No fixture/seed data files.** With one entity type and five meaningful
  fields, inline payloads via the factory read clearer than maintaining
  JSON fixtures on disk would. I'd revisit this if the domain model grows.
- **Explicit timestamps, never "now."** Every test payload specifies a
  fixed ISO timestamp. Keeps "latest report wins" and threshold-boundary
  assertions exact and reproducible instead of depending on wall-clock
  time.
- **The e2e layer intentionally skips per-test isolation.** It shares one
  live Postgres instance across a whole CI run — there's no cheap way to
  get a fresh Postgres per test the way SQLite allows — so e2e tests use
  `uuid4`-suffixed station IDs to dodge collisions rather than truncating
  tables between tests. That's a deliberate, documented trade-off (see the
  module docstring in `tests/e2e/test_docker_stack_smoke.py`), not an
  oversight. With only 4 e2e tests, table-truncation machinery would cost
  more than it buys.

---

## 4. CI/CD integration

`.github/workflows/ci.yml` runs on every pull request and every push to
`main`, as three sequential jobs:

1. **`lint`** (~10s) — `ruff check tests/ clients/ builder/ config/ conftest.py`.
   Fails fast on style/import issues before spending time on slower jobs.
2. **`unit-and-api-tests`** (needs `lint`) — installs `service/requirements.txt`
   plus `requirements-test.txt` on Python 3.11, runs
   `tests/unit + tests/api + tests/perf` with coverage, and uploads
   `coverage.xml`, `junit.xml`, and a self-contained HTML report (all under
   `reports/`) as build artifacts. This is the main merge gate: it needs
   zero external services and runs in under a second locally, so it's
   cheap to run on every commit, including WIP pushes.
3. **`e2e-docker`** (needs `unit-and-api-tests`) — starts the real
   docker-compose stack (Postgres + the API), polls `/health` until it's
   up, runs the `e2e`-marked tests against real HTTP, uploads an HTML
   report, dumps container logs on failure, and always tears the stack
   down. It's gated behind job 2 so a broken build fails in ~5s instead of
   burning ~1 minute spinning up Docker first.

   This job also installs `service/requirements.txt`, even though it only
   ever talks to the containerized app over HTTP. That's because the root
   `conftest.py` is an ancestor of `tests/e2e/`, and pytest always
   collects it regardless of which tests are selected — it imports
   `app.database`/`app.main` to wire up the unit/API fixtures, so without
   those dependencies installed, collection itself fails before a single
   e2e test runs. I found this the hard way on an actual CI run, not in
   local testing, since the e2e job had never previously needed to import
   the app at all.

I'd configure branch protection on `main` to require all three jobs before
merge (not something expressible in the workflow file itself). What's
intentionally **not** in CI: a dedicated load-test job (e.g. k6 against the
docker stack tracking p95 latency over time) — see [§5](#5-gaps--future-work).

---

## 5. Gaps & future work

- **Fix the duplicate-timestamp join bug** and flip the two `xfail` tests
  into plain assertions once `list_stations()` / `get_metrics_summary()`
  use a proper tiebreaker (e.g. `ORDER BY timestamp DESC, id DESC LIMIT 1`
  per station) instead of a `MAX(timestamp)`-equality join.
- **Real load/perf testing against the Postgres stack.** The
  `docker-compose.yml` sets `SIMULATED_LATENCY_MS=40` specifically to
  widen the request window and make write interleaving observable —
  that's the environment a real concurrency/perf harness (k6 or Locust,
  driving sustained concurrent writers against `/reports` while measuring
  p95/p99 and checking for lost or corrupted writes) belongs in. I didn't
  build this: it's explicitly out of scope per the assignment, and doing
  it properly is a multi-day investment in its own right, not something to
  half-build. `tests/perf/test_concurrency_smoke.py`'s docstring explains
  exactly why the current smoke test (SQLite, in-process, GIL-serialized)
  can't stand in for it.
- **Contract testing.** Once there's a real external consumer of this API
  (a NOC dashboard, another service), add an OpenAPI-diff check or
  `schemathesis` run to CI to catch breaking response-schema changes
  before they ship.
- **Mutation testing** (`mutmut`) on `scoring.py` to confirm the unit suite
  actually kills mutants, given how central that formula is to the whole
  service's purpose.
- **Data-volume behavior.** `/stations` has no pagination; nothing in this
  suite checks behavior with thousands of stations. Worth raising with the
  platform team independent of test coverage.
- **Parallelize the suite** with `pytest-xdist` once it's big enough that
  sub-second runtime stops being a given — the per-test DB isolation
  already makes this safe today.

### Assumptions made about service behavior

- `is_flagged` uses strict `<` against the threshold (a station scoring
  exactly 60 is healthy). I've treated this as intentional — it matches
  the doc comment "falls below" — and pinned it with an explicit boundary
  test.
- "Currently flagged" (`/stations/poor-hygiene`) is based on each
  station's **latest** report only, not its history — a station that was
  unhealthy and has since recovered shouldn't appear. Tested explicitly.
- A station gets created implicitly on its first `POST /reports` — there's
  no separate station-registration endpoint, so I've treated that as
  intended behavior rather than a gap.
- No authentication/authorization on any endpoint is treated as
  intentional for this exercise, not a defect to flag.
- The duplicate-timestamp double-counting ([§1](#1-approach)) I've judged
  a genuine defect, not a documented feature — nothing in the README or
  schema describes it, and it produces internally inconsistent output (one
  station reported with two different connectivity states "at once").

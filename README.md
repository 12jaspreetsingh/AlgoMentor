# AlgoMentor AI

A personal LeetCode accountability project, built incrementally while learning backend engineering.

**Current milestone: Phase 2 — FastAPI + PostgreSQL foundation.**

Implemented: validated configuration, pooled PostgreSQL connections, six initial models,
versioned migrations, health endpoints, and unit/integration tests. Submission entry,
goal tracking, Telegram, coaching, and the frontend belong to later phases.

## Run the existing workspace

The virtual environment and private `.env` have already been created locally. PostgreSQL
uses port **55432** to avoid interfering with an existing PostgreSQL service on 5432.

```bash
cd /home/jaspreet/algomentor-ai
source .venv/bin/activate
docker compose up -d --wait db
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Open [Swagger UI](http://127.0.0.1:8000/docs) to try the two health endpoints.
If an API process is already running on port 8000, use that process or stop it before
starting another; alternatively pass `--port 8001` and adjust the URLs.

## First setup on another machine

Prerequisites: Python 3.10+, its venv module, and Docker with the Compose plugin.
The tested environment uses Python 3.10 and PostgreSQL 17.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -c backend/requirements.lock -e './backend[dev]'
cp .env.example .env
```

Edit `.env` before starting PostgreSQL. Set a local password in both `POSTGRES_PASSWORD`
and `DATABASE_URL`; never commit `.env`. URL-encode special characters in the URL password.
Then run the database, migration, and Uvicorn commands above. The lock file records the
tested dependency versions; `pyproject.toml` describes supported dependency ranges.

Settings load the root `.env` regardless of the working directory. Actual environment
variables override `.env`. The app requires `postgresql+psycopg://…/database` and fails
early for a missing/invalid URL or unknown timezone.

This phase is local development only: bind the API and database to loopback. Owner
authentication and deployment hardening must be added before exposing personal data.

## Working HTTP demonstration

In a second terminal:

```bash
curl --fail-with-body http://127.0.0.1:8000/api/v1/health/live
curl --fail-with-body http://127.0.0.1:8000/api/v1/health/ready
```

Expected responses:

```json
{"status":"ok"}
```

```json
{"status":"ok","database":"reachable","schema_status":"current"}
```

Liveness answers whether the API process responds. Readiness connects to PostgreSQL and
checks that its Alembic revision matches this application's migration head. A missing
database or unapplied migration returns HTTP 503 without exposing connection details.
Readiness checks migration versions, not every table on every request; `alembic check`
is the separate schema drift check.

Inspect the real database without putting the password in a command:

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

At the PostgreSQL prompt:

```text
\dt
\d submissions
SELECT version_num FROM alembic_version;
SHOW timezone;
\q
```

There should be six application tables plus `alembic_version`, revision `0001`, and
session timezone `UTC`. No sample records are inserted into your development database.

## Run tests

Unit tests require no running database:

```bash
python -m pytest -c backend/pyproject.toml backend/tests/unit -q
```

For the complete suite, create a separate database **once**:

```bash
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" algomentor_test'
```

An "already exists" response means this step was previously completed. In `.env`, set
`TEST_DATABASE_URL` to the same server and credentials as `DATABASE_URL`, but change
the final database name to `algomentor_test`. This is already configured in this workspace.

```bash
python -m pytest -c backend/pyproject.toml backend/tests --require-postgres -q
ruff check backend
ruff format --check backend
alembic -c backend/alembic.ini check
python -m pip check
```

The tests require a database name ending in `_test`. Each integration test creates a
random schema, applies real migrations, and drops only that schema afterward. They
do not truncate the development database. Supply only a disposable test database;
the test database role needs permission to create schemas.

Without `TEST_DATABASE_URL`, the default suite skips integration tests explicitly.
`--require-postgres` turns missing test configuration into failure so a full verification
cannot silently pass without database coverage.

Coverage includes migration upgrade/downgrade/re-upgrade, model/schema agreement,
foreign keys, unique keys, repeated acceptances, nullable metadata, UTC timestamp
round trips, naive timestamp rejection, request-state constraints, and health failures.

## Stop and resume

Stop Uvicorn with `Ctrl+C` in its terminal. Stop PostgreSQL while preserving its volume:

```bash
docker compose stop db
```

Resume with the commands in "Run the existing workspace". Avoid `docker compose down -v`:
the `-v` flag deletes your database volume. Editing the password in `.env` does not
change the password of an already initialized PostgreSQL volume.

## Learn the implementation

Read [the Phase 2 guide](docs/phase-2.md) for the file map, data model, transaction
explanation, migration workflow, troubleshooting, and completion checklist.

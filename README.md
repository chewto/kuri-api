# CRM Core API

Multi-tenant CRM backend built with Flask and PostgreSQL.

## Requirements

- Python 3.11 (pinned in Render via `.python-version` and `PYTHON_VERSION=3.11.11`)
- PostgreSQL 16+ (Docker Compose or a local installation)
- Docker Desktop (optional, recommended)

## Local setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Adjust `DATABASE_URL` in `.env` if your credentials or PostgreSQL port do not
match the defaults.

## Local PostgreSQL

### Option A: Docker Compose

```powershell
docker compose up -d
docker compose ps
```

This creates:

- Development database: `crm_dev`
- Test database: `crm_test`
- User: `crm_user`
- Password: `crm_password`
- Host port: `5433` (to avoid colliding with a local PostgreSQL on `5432`)

The resulting URL is:

```text
postgresql://crm_user:crm_password@localhost:5433/crm_dev
```

### Option B: Existing PostgreSQL installation

Run as a superuser:

```sql
CREATE ROLE crm_user LOGIN PASSWORD 'crm_password';
CREATE DATABASE crm_dev OWNER crm_user;
CREATE DATABASE crm_test OWNER crm_user;
```

Make sure `DATABASE_URL` in `.env` points at that instance. If you use the local
PostgreSQL on port `5432`, change the URL to:

```text
postgresql://crm_user:crm_password@localhost:5432/crm_dev
```

## Migrations

With PostgreSQL available:

```powershell
.\.venv\Scripts\flask.exe --app wsgi db upgrade
```

To check the current state:

```powershell
.\.venv\Scripts\flask.exe --app wsgi db current
```

You can also validate the full cycle against an empty database:

```powershell
.\.venv\Scripts\flask.exe --app wsgi db downgrade base
.\.venv\Scripts\flask.exe --app wsgi db upgrade
```

### Creating the tables manually (optional)

The recommended path is to let `flask db upgrade` create the schema. On Render
this already happens when the service starts.

If you prefer to run the SQL directly against an **empty** database, the script
generated from the migrations lives in
[`scripts/schema_postgres.sql`](scripts/schema_postgres.sql):

```powershell
psql "<RENDER_EXTERNAL_DATABASE_URL>" -f scripts/schema_postgres.sql
```

You can obtain the external URL in Render → PostgreSQL → Connect. The script
includes `alembic_version` at revision `c38a2e1f4092`, so a later
`flask db upgrade` will not recreate the tables. The follow-up migration
`a1b2c3d4e5f6` then renames any legacy default pipeline stages to English.

Do not run it if the database already has tables; in that case use
`flask db upgrade`, or `flask db stamp head` when the schema exists but
`alembic_version` is missing.

## Running the API

```powershell
.\.venv\Scripts\flask.exe --app wsgi run --debug
```

Health check: `http://127.0.0.1:5000/health`

## Migrating data from SQLite

The script copies data from `instance/crm_dev.db` to the PostgreSQL database
configured in `DATABASE_URL`. **Stop the API before running it.**

1. Back up the SQLite file.
2. Make sure the target schema is up to date (`flask db upgrade`).
3. Review the plan without writing:

```powershell
.\.venv\Scripts\python.exe -m scripts.migrate_sqlite_to_postgres --dry-run
```

4. Run the copy:

```powershell
.\.venv\Scripts\python.exe -m scripts.migrate_sqlite_to_postgres
```

Useful options:

- `--reset`: clears the domain tables before copying.
- `--drop-orphans`: skips rows whose required foreign keys do not exist
  (SQLite did not enforce referential integrity).
- `--source` and `--target`: alternative paths/URLs.

The script converts booleans, dates, timestamps (assuming UTC when no timezone
is present), amounts, and enums, and verifies row counts when finished. It does
not copy `alembic_version`.

## Tests

By default the tests use in-memory SQLite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

To run them against PostgreSQL:

```powershell
$env:TEST_DATABASE_URL = "postgresql://crm_user:crm_password@localhost:5433/crm_test"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:TEST_DATABASE_URL
```

## Deploying to Render

`render.yaml` already defines the PostgreSQL database and runs
`flask db upgrade` when the service starts. Render's free tier does not support
`preDeployCommand`, so migrations are applied at startup.

Before the first deployment, if the Render database already has tables without
an `alembic_version` row, run this once against the external Render URL:

```powershell
$env:DATABASE_URL = "<Render External Database URL>"
.\.venv\Scripts\flask.exe --app wsgi db stamp head
```

If the Docker volume already existed without the `crm_test` database, create it
manually:

```powershell
docker compose exec postgres createdb -U crm_user crm_test
```

## Key structure

- `app/config.py`: database, JWT, and CORS configuration.
- `migrations/`: Alembic history.
- `scripts/migrate_sqlite_to_postgres.py`: SQLite → PostgreSQL data copy.
- `docker-compose.yml`: local PostgreSQL.
- `tests/`: test suite.

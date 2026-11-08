# CRM Core API

Backend Flask del CRM multi-tenant. Usa PostgreSQL como base de datos.

## Requisitos

- Python 3.11 (en Render se fija con `.python-version` y `PYTHON_VERSION=3.11.11`)
- PostgreSQL 16+ (Docker Compose o instalación local)
- Docker Desktop (opcional, recomendado)

## Configuración local

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Ajusta `DATABASE_URL` en `.env` si tus credenciales o el puerto de PostgreSQL
no coinciden con el valor por defecto.

## PostgreSQL local

### Opción A: Docker Compose

```powershell
docker compose up -d
docker compose ps
```

Esto crea:

- Base de datos: `crm_dev`
- Base de datos de tests: `crm_test`
- Usuario: `crm_user`
- Contraseña: `crm_password`
- Puerto del host: `5433` (para no chocar con un PostgreSQL local en `5432`)

La URL resultante es:

```text
postgresql://crm_user:crm_password@localhost:5433/crm_dev
```

### Opción B: PostgreSQL ya instalado

Ejecuta como superusuario:

```sql
CREATE ROLE crm_user LOGIN PASSWORD 'crm_password';
CREATE DATABASE crm_dev OWNER crm_user;
CREATE DATABASE crm_test OWNER crm_user;
```

Asegúrate de que `DATABASE_URL` en `.env` apunte a esa instancia. Si usas el
PostgreSQL local del puerto `5432`, cambia la URL a:

```text
postgresql://crm_user:crm_password@localhost:5432/crm_dev
```

## Migraciones

Con PostgreSQL disponible:

```powershell
.\.venv\Scripts\flask.exe --app wsgi db upgrade
```

Para comprobar el estado:

```powershell
.\.venv\Scripts\flask.exe --app wsgi db current
```

También puedes probar el ciclo completo contra una base vacía:

```powershell
.\.venv\Scripts\flask.exe --app wsgi db downgrade base
.\.venv\Scripts\flask.exe --app wsgi db upgrade
```

### Crear las tablas manualmente (opcional)

El camino recomendado es dejar que `flask db upgrade` cree el esquema. En
Render eso ya ocurre en el arranque del servicio.

Si prefieres ejecutar el SQL directamente sobre una base **vacía**, el script
generado desde las migraciones está en
[`scripts/schema_postgres.sql`](scripts/schema_postgres.sql):

```powershell
psql "<EXTERNAL_DATABASE_URL_DE_RENDER>" -f scripts/schema_postgres.sql
```

La URL externa se obtiene en Render → PostgreSQL → Connect. El script incluye
`alembic_version` con la revisión `c38a2e1f4092`, por lo que un posterior
`flask db upgrade` no vuelve a crear las tablas.

No lo ejecutes si la base ya tiene tablas: en ese caso usa `flask db upgrade`
o, si el esquema ya existe pero falta `alembic_version`, `flask db stamp head`.

## Ejecutar la API

```powershell
.\.venv\Scripts\flask.exe --app wsgi run --debug
```

Health check: `http://127.0.0.1:5000/health`

## Migrar datos desde SQLite

El script copia los datos de `instance/crm_dev.db` a la base PostgreSQL
configurada en `DATABASE_URL`. **Detén la API antes de ejecutarlo.**

1. Haz una copia de seguridad del archivo SQLite.
2. Asegúrate de que el esquema destino esté al día (`flask db upgrade`).
3. Revisa el plan sin escribir:

```powershell
.\.venv\Scripts\python.exe -m scripts.migrate_sqlite_to_postgres --dry-run
```

4. Ejecuta la copia:

```powershell
.\.venv\Scripts\python.exe -m scripts.migrate_sqlite_to_postgres
```

Opciones útiles:

- `--reset`: vacía las tablas de dominio antes de copiar.
- `--drop-orphans`: omite filas con FKs obligatorias inexistentes (SQLite no
  aplicaba integridad referencial).
- `--source` y `--target`: rutas/URLs alternativas.

El script convierte booleanos, fechas, timestamps (asumiendo UTC cuando no
traen zona), montos y enums, y verifica los conteos al finalizar. No copia
`alembic_version`.

## Tests

Por defecto los tests usan SQLite en memoria:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Para ejecutarlos contra PostgreSQL:

```powershell
$env:TEST_DATABASE_URL = "postgresql://crm_user:crm_password@localhost:5433/crm_test"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:TEST_DATABASE_URL
```

## Despliegue en Render

`render.yaml` ya define la base PostgreSQL y ejecuta `flask db upgrade` al
iniciar el servicio. Render free no soporta `preDeployCommand`, por eso las
migraciones se aplican en el arranque.

Antes del primer despliegue, si la base de Render ya tuviera tablas creadas sin
`alembic_version`, ejecuta una vez contra la URL externa de Render:

```powershell
$env:DATABASE_URL = "<External Database URL de Render>"
.\.venv\Scripts\flask.exe --app wsgi db stamp head
```

Si el volumen de Docker ya existía sin la base `crm_test`, créala manualmente:

```powershell
docker compose exec postgres createdb -U crm_user crm_test
```

## Estructura relevante

- `app/config.py`: configuración de base de datos, JWT y CORS.
- `migrations/`: historial Alembic.
- `scripts/migrate_sqlite_to_postgres.py`: copia de datos SQLite → PostgreSQL.
- `docker-compose.yml`: PostgreSQL local.
- `tests/`: suite de tests.

"""Copia los datos de la base SQLite local a PostgreSQL.

Uso típico (desde la raíz del repositorio):

    python -m scripts.migrate_sqlite_to_postgres --dry-run
    python -m scripts.migrate_sqlite_to_postgres

El esquema destino debe existir antes de ejecutar este script:

    flask db upgrade

El script no copia ``alembic_version``: esa tabla la administra Alembic.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, func, inspect, select, text

from app.config import normalize_database_url
from scripts.migration_utils import coerce_row, filter_orphans

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "instance" / "crm_dev.db"

TABLE_ORDER = [
    "tenants",
    "users",
    "companies",
    "contacts",
    "categories",
    "stages",
    "activity_logs",
    "subscriptions",
    "transactions",
    "deals",
]

# columna FK -> (tabla padre, es_nullable)
FOREIGN_KEYS: dict[str, dict[str, tuple[str, bool]]] = {
    "users": {"tenant_id": ("tenants", False)},
    "companies": {"tenant_id": ("tenants", False)},
    "contacts": {
        "tenant_id": ("tenants", False),
        "company_id": ("companies", True),
    },
    "categories": {"tenant_id": ("tenants", False)},
    "stages": {"tenant_id": ("tenants", False)},
    "activity_logs": {
        "tenant_id": ("tenants", False),
        "contact_id": ("contacts", False),
        "user_id": ("users", True),
    },
    "subscriptions": {
        "tenant_id": ("tenants", False),
        "company_id": ("companies", True),
        "category_id": ("categories", True),
    },
    "transactions": {
        "tenant_id": ("tenants", False),
        "category_id": ("categories", True),
        "company_id": ("companies", True),
    },
    "deals": {
        "tenant_id": ("tenants", False),
        "company_id": ("companies", False),
        "contact_id": ("contacts", True),
        "stage_id": ("stages", False),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copia datos de instance/crm_dev.db (SQLite) a PostgreSQL.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Ruta del archivo SQLite (por defecto: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="URL de PostgreSQL. Por defecto se usa DATABASE_URL.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Vacía las tablas destino antes de copiar (TRUNCATE ... CASCADE).",
    )
    parser.add_argument(
        "--drop-orphans",
        action="store_true",
        help="Omite filas con FKs obligatorias inexistentes en lugar de abortar.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el plan y los conteos sin escribir en PostgreSQL.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Filas por lote al insertar (por defecto: 500).",
    )
    return parser.parse_args()


def load_source_rows(source_path: Path) -> tuple[sqlite3.Connection, dict[str, list[dict[str, Any]]]]:
    if not source_path.exists():
        raise FileNotFoundError(f"No existe el archivo SQLite: {source_path}")

    connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = [table for table in TABLE_ORDER if table not in tables]
    if missing:
        raise RuntimeError(
            "La base SQLite no tiene las tablas esperadas: " + ", ".join(missing)
        )

    rows: dict[str, list[dict[str, Any]]] = {}
    for table_name in TABLE_ORDER:
        cursor = connection.execute(f'SELECT * FROM "{table_name}"')
        rows[table_name] = [dict(row) for row in cursor.fetchall()]

    return connection, rows


def target_counts(connection, metadata: MetaData) -> dict[str, int]:
    return {
        table_name: connection.execute(
            select(func.count()).select_from(metadata.tables[table_name])
        ).scalar_one()
        for table_name in TABLE_ORDER
    }


def table_enums(metadata: MetaData, table_name: str) -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    for column in metadata.tables[table_name].columns:
        values = getattr(column.type, "enums", None)
        if values:
            enums[column.name] = list(values)
    return enums


def prepare_rows(
    source_rows: dict[str, list[dict[str, Any]]],
    metadata: MetaData,
    drop_orphans: bool,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[str]]:
    """Convierte y valida las filas en orden de dependencias."""
    prepared: dict[str, list[dict[str, Any]]] = {}
    ids_by_table: dict[str, set[str]] = {}
    warnings: list[str] = []
    orphan_samples: list[str] = []

    for table_name in TABLE_ORDER:
        table = metadata.tables[table_name]
        column_types = {column.name: column.type for column in table.columns}
        source_columns = set(source_rows[table_name][0].keys()) if source_rows[table_name] else set()
        extra_columns = source_columns.difference(table.columns.keys())
        if extra_columns:
            warnings.append(
                f"{table_name}: columnas de SQLite ignoradas: {', '.join(sorted(extra_columns))}"
            )

        coerced_rows = [
            coerce_row(row, column_types) for row in source_rows[table_name]
        ]

        fk_specs = {
            column: nullable
            for column, (_, nullable) in FOREIGN_KEYS.get(table_name, {}).items()
        }
        parent_ids = {
            column: ids_by_table.get(parent_table, set())
            for column, (parent_table, _) in FOREIGN_KEYS.get(table_name, {}).items()
        }

        kept, dropped, table_warnings = filter_orphans(
            coerced_rows, parent_ids, fk_specs
        )
        warnings.extend(f"{table_name}: {message}" for message in table_warnings)

        if dropped and not drop_orphans:
            orphan_samples.extend(
                f"{table_name}: {row.get('id', '<sin id>')}" for row in dropped[:10]
            )

        # Validar valores de enums nativos de PostgreSQL.
        enum_columns = table_enums(metadata, table_name)
        for row in kept:
            for column_name, allowed_values in enum_columns.items():
                value = row.get(column_name)
                if value is not None and value not in allowed_values:
                    raise ValueError(
                        f"{table_name}.{column_name}={value!r} no está en el enum "
                        f"de PostgreSQL {allowed_values}"
                    )

        # Validar columnas NOT NULL que lleguen vacías.
        for row in kept:
            for column in table.columns:
                if not column.nullable and row.get(column.name) is None:
                    raise ValueError(
                        f"{table_name}.{column.name} es NOT NULL pero la fila "
                        f"{row.get('id', '<sin id>')} llega vacía"
                    )

        prepared[table_name] = kept
        primary_key_columns = [column.name for column in table.primary_key.columns]
        if len(primary_key_columns) != 1:
            raise RuntimeError(f"{table_name} no tiene una PK simple.")
        pk = primary_key_columns[0]
        ids_by_table[table_name] = {str(row[pk]) for row in kept}

    return prepared, warnings, orphan_samples


def truncate_target(connection, metadata: MetaData) -> None:
    table_list = ", ".join(f'"{table_name}"' for table_name in reversed(TABLE_ORDER))
    connection.execute(
        text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
    )


def main() -> int:
    # Evita errores de encoding en consolas de Windows con code pages antiguas.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()

    target_url = args.target or os.getenv("DATABASE_URL")
    if not target_url:
        print(
            "ERROR: define DATABASE_URL o pasa --target con la URL de PostgreSQL.",
            file=sys.stderr,
        )
        return 1
    target_url = normalize_database_url(target_url)

    source_connection = None
    engine = None
    try:
        source_connection, source_rows = load_source_rows(args.source)
        engine = create_engine(target_url, pool_pre_ping=True)

        if engine.dialect.name != "postgresql":
            print(
                "ERROR: el destino debe ser PostgreSQL. "
                f"Se recibió el dialecto '{engine.dialect.name}'.",
                file=sys.stderr,
            )
            return 1

        metadata = MetaData()
        metadata.reflect(bind=engine, only=TABLE_ORDER)
        missing_tables = [
            table_name for table_name in TABLE_ORDER if table_name not in metadata.tables
        ]
        if missing_tables:
            print(
                "ERROR: faltan tablas en PostgreSQL: "
                + ", ".join(missing_tables)
                + ". Ejecuta 'flask db upgrade' primero.",
                file=sys.stderr,
            )
            return 1

        if not inspect(engine).has_table("alembic_version"):
            print(
                "ERROR: PostgreSQL no tiene la tabla alembic_version. "
                "Ejecuta 'flask db upgrade' primero.",
                file=sys.stderr,
            )
            return 1

        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        if version is None:
            print(
                "ERROR: PostgreSQL no tiene versión de Alembic. "
                "Ejecuta 'flask db upgrade' primero.",
                file=sys.stderr,
            )
            return 1

        prepared, warnings, orphan_samples = prepare_rows(
            source_rows, metadata, args.drop_orphans
        )

        if orphan_samples and not args.drop_orphans:
            print(
                "ERROR: hay filas con FKs obligatorias que no existen en SQLite "
                "(la integridad referencial estaba desactivada).",
                file=sys.stderr,
            )
            for sample in orphan_samples:
                print(f"  - {sample}", file=sys.stderr)
            print(
                "Revisa los datos o ejecuta con --drop-orphans para omitir esas filas.",
                file=sys.stderr,
            )
            return 2

        with engine.connect() as connection:
            current_counts = target_counts(connection, metadata)

        non_empty = {
            table_name: count
            for table_name, count in current_counts.items()
            if count > 0
        }
        if non_empty and not args.reset:
            print(
                "ERROR: PostgreSQL ya contiene datos. Usa --reset para vaciar "
                "las tablas antes de copiar.",
                file=sys.stderr,
            )
            for table_name, count in non_empty.items():
                print(f"  - {table_name}: {count}", file=sys.stderr)
            return 1

        print(f"Origen : {args.source}")
        print(f"Destino: {engine.url.render_as_string(hide_password=True)}")
        print(f"Alembic: {version}")
        print("\nConteos a copiar:")
        for table_name in TABLE_ORDER:
            print(
                f"  {table_name:<15} SQLite={len(source_rows[table_name]):>5} "
                f"-> destino={len(prepared[table_name]):>5}"
            )

        if warnings:
            print(f"\nAdvertencias ({len(warnings)}):")
            for warning in warnings[:20]:
                print(f"  - {warning}")
            if len(warnings) > 20:
                print(f"  ... y {len(warnings) - 20} más.")

        if args.dry_run:
            print("\nDry-run: no se escribió nada en PostgreSQL.")
            return 0

        with engine.begin() as connection:
            if args.reset:
                truncate_target(connection, metadata)

            for table_name in TABLE_ORDER:
                rows = prepared[table_name]
                if not rows:
                    continue
                table = metadata.tables[table_name]
                for start in range(0, len(rows), args.batch_size):
                    connection.execute(
                        table.insert(), rows[start : start + args.batch_size]
                    )
                print(f"Copiada {table_name}: {len(rows)} filas")

        with engine.connect() as connection:
            final_counts = target_counts(connection, metadata)

        mismatches = {
            table_name: (len(prepared[table_name]), final_counts[table_name])
            for table_name in TABLE_ORDER
            if len(prepared[table_name]) != final_counts[table_name]
        }
        if mismatches:
            print("\nERROR: los conteos finales no coinciden:", file=sys.stderr)
            for table_name, (expected, actual) in mismatches.items():
                print(
                    f"  - {table_name}: esperado {expected}, encontrado {actual}",
                    file=sys.stderr,
                )
            return 1

        print("\nCopia completada correctamente.")
        for table_name in TABLE_ORDER:
            print(f"  {table_name:<15} {final_counts[table_name]:>5}")
        return 0

    except Exception as exc:  # noqa: BLE001 - reporte amigable para un CLI
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if source_connection is not None:
            source_connection.close()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

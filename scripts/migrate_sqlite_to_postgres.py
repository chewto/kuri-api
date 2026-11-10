"""Copy data from the local SQLite database to PostgreSQL.

Typical usage (from the repository root):

    python -m scripts.migrate_sqlite_to_postgres --dry-run
    python -m scripts.migrate_sqlite_to_postgres

The target schema must exist before running this script:

    flask db upgrade

The script does not copy ``alembic_version``: Alembic manages that table.
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

# FK column -> (parent table, is_nullable)
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
        description="Copy data from instance/crm_dev.db (SQLite) to PostgreSQL.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Path to the SQLite file (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate the target tables before copying (TRUNCATE ... CASCADE).",
    )
    parser.add_argument(
        "--drop-orphans",
        action="store_true",
        help="Skip rows with missing required FKs instead of aborting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the plan and counts without writing to PostgreSQL.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per insert batch (default: 500).",
    )
    return parser.parse_args()


def load_source_rows(source_path: Path) -> tuple[sqlite3.Connection, dict[str, list[dict[str, Any]]]]:
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite file does not exist: {source_path}")

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
            "The SQLite database is missing the expected tables: " + ", ".join(missing)
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
    """Convert and validate rows in dependency order."""
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
                f"{table_name}: ignored SQLite columns: {', '.join(sorted(extra_columns))}"
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
                f"{table_name}: {row.get('id', '<no id>')}" for row in dropped[:10]
            )

        # Validate native PostgreSQL enum values.
        enum_columns = table_enums(metadata, table_name)
        for row in kept:
            for column_name, allowed_values in enum_columns.items():
                value = row.get(column_name)
                if value is not None and value not in allowed_values:
                    raise ValueError(
                        f"{table_name}.{column_name}={value!r} is not in the PostgreSQL "
                        f"enum {allowed_values}"
                    )

        # Validate NOT NULL columns that arrive empty.
        for row in kept:
            for column in table.columns:
                if not column.nullable and row.get(column.name) is None:
                    raise ValueError(
                        f"{table_name}.{column.name} is NOT NULL but row "
                        f"{row.get('id', '<no id>')} arrives empty"
                    )

        prepared[table_name] = kept
        primary_key_columns = [column.name for column in table.primary_key.columns]
        if len(primary_key_columns) != 1:
            raise RuntimeError(f"{table_name} does not have a simple PK.")
        pk = primary_key_columns[0]
        ids_by_table[table_name] = {str(row[pk]) for row in kept}

    return prepared, warnings, orphan_samples


def truncate_target(connection, metadata: MetaData) -> None:
    table_list = ", ".join(f'"{table_name}"' for table_name in reversed(TABLE_ORDER))
    connection.execute(
        text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
    )


def main() -> int:
    # Avoid encoding errors on Windows consoles with legacy code pages.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()

    target_url = args.target or os.getenv("DATABASE_URL")
    if not target_url:
        print(
            "ERROR: set DATABASE_URL or pass --target with the PostgreSQL URL.",
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
                "ERROR: the target must be PostgreSQL. "
                f"Received dialect '{engine.dialect.name}'.",
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
                "ERROR: missing tables in PostgreSQL: "
                + ", ".join(missing_tables)
                + ". Run 'flask db upgrade' first.",
                file=sys.stderr,
            )
            return 1

        if not inspect(engine).has_table("alembic_version"):
            print(
                "ERROR: PostgreSQL does not have the alembic_version table. "
                "Run 'flask db upgrade' first.",
                file=sys.stderr,
            )
            return 1

        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        if version is None:
            print(
                "ERROR: PostgreSQL has no Alembic version. "
                "Run 'flask db upgrade' first.",
                file=sys.stderr,
            )
            return 1

        prepared, warnings, orphan_samples = prepare_rows(
            source_rows, metadata, args.drop_orphans
        )

        if orphan_samples and not args.drop_orphans:
            print(
                "ERROR: some rows have required FKs that do not exist in SQLite "
                "(referential integrity was disabled).",
                file=sys.stderr,
            )
            for sample in orphan_samples:
                print(f"  - {sample}", file=sys.stderr)
            print(
                "Review the data or run with --drop-orphans to skip those rows.",
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
                "ERROR: PostgreSQL already contains data. Use --reset to truncate "
                "the tables before copying.",
                file=sys.stderr,
            )
            for table_name, count in non_empty.items():
                print(f"  - {table_name}: {count}", file=sys.stderr)
            return 1

        print(f"Source : {args.source}")
        print(f"Target: {engine.url.render_as_string(hide_password=True)}")
        print(f"Alembic: {version}")
        print("\nCounts to copy:")
        for table_name in TABLE_ORDER:
            print(
                f"  {table_name:<15} SQLite={len(source_rows[table_name]):>5} "
                f"-> target={len(prepared[table_name]):>5}"
            )

        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for warning in warnings[:20]:
                print(f"  - {warning}")
            if len(warnings) > 20:
                print(f"  ... and {len(warnings) - 20} more.")

        if args.dry_run:
            print("\nDry-run: nothing was written to PostgreSQL.")
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
                print(f"Copied {table_name}: {len(rows)} rows")

        with engine.connect() as connection:
            final_counts = target_counts(connection, metadata)

        mismatches = {
            table_name: (len(prepared[table_name]), final_counts[table_name])
            for table_name in TABLE_ORDER
            if len(prepared[table_name]) != final_counts[table_name]
        }
        if mismatches:
            print("\nERROR: final counts do not match:", file=sys.stderr)
            for table_name, (expected, actual) in mismatches.items():
                print(
                    f"  - {table_name}: expected {expected}, found {actual}",
                    file=sys.stderr,
                )
            return 1

        print("\nCopy completed successfully.")
        for table_name in TABLE_ORDER:
            print(f"  {table_name:<15} {final_counts[table_name]:>5}")
        return 0

    except Exception as exc:  # noqa: BLE001 - user-friendly CLI reporting
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if source_connection is not None:
            source_connection.close()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

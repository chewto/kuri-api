"""Pure helpers for the SQLite -> PostgreSQL data copy.

They are kept separate from the main script so they can be tested without a
real database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text


def to_boolean(value: Any) -> bool | None:
    """Convert SQLite 0/1 values (or text) to a PostgreSQL boolean."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"Unrecognized boolean value: {value!r}")


def to_datetime(value: Any) -> datetime | None:
    """Convert SQLite text to a timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid date/time: {value!r}") from exc

    if parsed.tzinfo is None:
        # SQLite stored datetimes without a timezone; the backend always wrote
        # them with datetime.now(timezone.utc), so the clock is UTC.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_date(value: Any) -> date | None:
    """Convert SQLite text to a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value!r}") from exc


def to_decimal(value: Any) -> Decimal | None:
    """Convert amounts to Decimal for PostgreSQL NUMERIC columns."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_text(value: Any) -> str | None:
    """Normalize SQLite strings and blobs to text."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def coerce_row(row: Mapping[str, Any], column_types: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the appropriate conversion based on the target column type."""
    converted: dict[str, Any] = {}

    for name, value in row.items():
        column_type = column_types.get(name)
        if column_type is None:
            continue

        if isinstance(column_type, Boolean):
            converted[name] = to_boolean(value)
        elif isinstance(column_type, DateTime):
            converted[name] = to_datetime(value)
        elif isinstance(column_type, Date):
            converted[name] = to_date(value)
        elif isinstance(column_type, Numeric):
            converted[name] = to_decimal(value)
        elif isinstance(column_type, Integer):
            converted[name] = None if value is None else int(value)
        elif isinstance(column_type, (String, Text)):
            converted[name] = to_text(value)
        else:
            converted[name] = value

    return converted


def filter_orphans(
    rows: Iterable[Mapping[str, Any]],
    parent_ids: Mapping[str, set[str]],
    foreign_keys: Mapping[str, bool],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Filter rows whose required FKs do not exist in the target.

    ``foreign_keys`` maps column -> is_nullable. If the FK is nullable and the
    parent does not exist, it is set to ``NULL`` (equivalent to
    ``ON DELETE SET NULL``). If it is required, the row is dropped and reported.

    Returns ``(valid_rows, dropped_rows, warnings)``.
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for original in rows:
        row = dict(original)
        drop_row = False

        for column, nullable in foreign_keys.items():
            value = row.get(column)
            if value is None:
                continue

            valid_ids = parent_ids.get(column, set())
            if value in valid_ids:
                continue

            if nullable:
                row[column] = None
                warnings.append(
                    f"FK '{column}' has no parent ({value!r}); it will be copied as NULL."
                )
            else:
                dropped.append(row)
                warnings.append(
                    f"Row dropped: required FK '{column}' has no parent ({value!r})."
                )
                drop_row = True
                break

        if not drop_row:
            kept.append(row)

    return kept, dropped, warnings

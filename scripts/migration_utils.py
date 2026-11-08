"""Utilidades puras para la copia de datos SQLite -> PostgreSQL.

Se mantienen separadas del script principal para poder probarlas sin una base
de datos real.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text


def to_boolean(value: Any) -> bool | None:
    """Convierte los 0/1 de SQLite (o texto) a booleano de PostgreSQL."""
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
    raise ValueError(f"Valor booleano no reconocido: {value!r}")


def to_datetime(value: Any) -> datetime | None:
    """Convierte el texto de SQLite a datetime con zona horaria UTC."""
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
            raise ValueError(f"Fecha/hora inválida: {value!r}") from exc

    if parsed.tzinfo is None:
        # SQLite guardaba los datetime sin zona; el backend siempre escribió
        # con datetime.now(timezone.utc), por lo que el reloj es UTC.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_date(value: Any) -> date | None:
    """Convierte el texto de SQLite a date."""
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
        raise ValueError(f"Fecha inválida: {value!r}") from exc


def to_decimal(value: Any) -> Decimal | None:
    """Convierte montos a Decimal para columnas NUMERIC de PostgreSQL."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_text(value: Any) -> str | None:
    """Normaliza strings y blobs de SQLite a texto."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def coerce_row(row: Mapping[str, Any], column_types: Mapping[str, Any]) -> dict[str, Any]:
    """Aplica la conversión adecuada según el tipo de la columna destino."""
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
    """Filtra filas cuyas FKs obligatorias no existen en el destino.

    ``foreign_keys`` mapea columna -> es_nullable. Si la FK es nullable y el
    padre no existe, se deja en ``NULL`` (equivalente al ``ON DELETE SET NULL``).
    Si es obligatoria, la fila se descarta y se reporta.

    Devuelve ``(filas_validas, filas_descartadas, advertencias)``.
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
                    f"FK '{column}' sin padre ({value!r}); se copiará como NULL."
                )
            else:
                dropped.append(row)
                warnings.append(
                    f"Fila descartada: FK obligatoria '{column}' sin padre ({value!r})."
                )
                drop_row = True
                break

        if not drop_row:
            kept.append(row)

    return kept, dropped, warnings

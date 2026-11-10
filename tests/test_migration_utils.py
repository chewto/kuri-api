import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String

from scripts.migration_utils import (
    coerce_row,
    filter_orphans,
    to_boolean,
    to_date,
    to_datetime,
    to_decimal,
)


class ConversionTests(unittest.TestCase):
    def test_boolean_values(self):
        self.assertIs(to_boolean(1), True)
        self.assertIs(to_boolean(0), False)
        self.assertIs(to_boolean("true"), True)
        self.assertIs(to_boolean("false"), False)
        self.assertIsNone(to_boolean(None))

        with self.assertRaises(ValueError):
            to_boolean("maybe")

    def test_naive_datetime_is_assumed_utc(self):
        value = to_datetime("2026-10-13 03:11:19.827706")
        self.assertEqual(value.tzinfo, timezone.utc)
        self.assertEqual(value.isoformat(), "2026-10-13T03:11:19.827706+00:00")

    def test_aware_datetime_is_converted_to_utc(self):
        value = to_datetime("2026-10-13T05:11:19+02:00")
        self.assertEqual(value.isoformat(), "2026-10-13T03:11:19+00:00")

    def test_date_value(self):
        self.assertEqual(to_date("2026-11-01"), date(2026, 11, 1))
        self.assertIsNone(to_date(None))

    def test_decimal_value(self):
        self.assertEqual(to_decimal(14000), Decimal("14000"))
        self.assertEqual(to_decimal("1234.56"), Decimal("1234.56"))
        self.assertIsNone(to_decimal(None))

    def test_coerce_row_uses_target_column_types(self):
        row = {
            "id": "abc",
            "is_active": 1,
            "created_at": "2026-10-13 03:11:19",
            "due_date": "2026-11-01",
            "amount": 14000,
        }
        column_types = {
            "id": String(36),
            "is_active": Boolean(),
            "created_at": DateTime(timezone=True),
            "due_date": Date(),
            "amount": Numeric(10, 2),
            "order": Integer(),
        }

        converted = coerce_row(row, column_types)

        self.assertEqual(converted["id"], "abc")
        self.assertIs(converted["is_active"], True)
        self.assertEqual(converted["created_at"].tzinfo, timezone.utc)
        self.assertEqual(converted["due_date"], date(2026, 11, 1))
        self.assertEqual(converted["amount"], Decimal("14000"))
        self.assertNotIn("order", converted)


class OrphanFilterTests(unittest.TestCase):
    def test_nullable_fk_is_set_to_null(self):
        rows = [{"id": "1", "tenant_id": "t1", "company_id": "missing"}]
        kept, dropped, warnings = filter_orphans(
            rows,
            {"tenant_id": {"t1"}, "company_id": {"c1"}},
            {"tenant_id": False, "company_id": True},
        )

        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["company_id"], None)
        self.assertEqual(dropped, [])
        self.assertTrue(warnings)

    def test_required_fk_drops_row(self):
        rows = [{"id": "1", "tenant_id": "missing"}]
        kept, dropped, warnings = filter_orphans(
            rows,
            {"tenant_id": {"t1"}},
            {"tenant_id": False},
        )

        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["id"], "1")
        self.assertTrue(warnings)

    def test_valid_rows_are_kept(self):
        rows = [{"id": "1", "tenant_id": "t1", "company_id": None}]
        kept, dropped, warnings = filter_orphans(
            rows,
            {"tenant_id": {"t1"}, "company_id": set()},
            {"tenant_id": False, "company_id": True},
        )

        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()

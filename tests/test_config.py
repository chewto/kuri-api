import unittest

from app.config import normalize_database_url


class NormalizeDatabaseUrlTests(unittest.TestCase):
    def test_render_postgres_scheme_is_normalized(self):
        self.assertEqual(
            normalize_database_url("postgres://user:pass@host:5432/db"),
            "postgresql+psycopg2://user:pass@host:5432/db",
        )

    def test_postgresql_scheme_uses_psycopg2(self):
        self.assertEqual(
            normalize_database_url("postgresql://user:pass@host:5432/db"),
            "postgresql+psycopg2://user:pass@host:5432/db",
        )

    def test_explicit_driver_is_kept(self):
        url = "postgresql+psycopg2://user:pass@host:5432/db"
        self.assertEqual(normalize_database_url(url), url)

    def test_sqlite_url_is_kept(self):
        url = "sqlite:///:memory:"
        self.assertEqual(normalize_database_url(url), url)


if __name__ == "__main__":
    unittest.main()

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://crm_user:crm_password@localhost:5433/crm_dev"


def normalize_database_url(raw_database_url: str) -> str:
    """Normalizes the connection URL so SQLAlchemy uses psycopg2.

    Render has historically provided ``postgres://``. In addition, as of
    SQLAlchemy 2.1 the ``postgresql://`` scheme selects psycopg 3 by
    default; the project ships ``psycopg2-binary``, so the driver is set
    explicitly.
    """
    if raw_database_url.startswith("postgres://"):
        raw_database_url = raw_database_url.replace(
            "postgres://", "postgresql://", 1
        )

    if raw_database_url.startswith("postgresql://"):
        raw_database_url = "postgresql+psycopg2://" + raw_database_url[
            len("postgresql://") :
        ]

    return raw_database_url


class Config:
    """Shared base configuration."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-crm-2026")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-crm-2026")

    # Token expiration times
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Database configuration
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Avoid stale connections after PostgreSQL restarts (local or Render).
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # CORS configuration
    raw_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173")
    CORS_ORIGINS = [origin.strip() for origin in raw_cors.split(",") if origin.strip()]


class DevelopmentConfig(Config):
    """Configuration for local development."""

    DEBUG = True
    ENV = "development"


class ProductionConfig(Config):
    """Configuration for the production environment."""

    DEBUG = False
    ENV = "production"


class TestingConfig(Config):
    """Configuration for automated test runs."""

    TESTING = True
    # In-memory SQLite by default; TEST_DATABASE_URL allows running the suite
    # against PostgreSQL without changing code.
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    )
    JWT_SECRET_KEY = "test-jwt-secret-key-32-bytes-secure-hash-crm"


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}

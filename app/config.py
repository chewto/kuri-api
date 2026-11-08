import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://crm_user:crm_password@localhost:5433/crm_dev"


def normalize_database_url(raw_database_url: str) -> str:
    """Normaliza la URL de conexión para que SQLAlchemy use psycopg2.

    Render entrega históricamente ``postgres://``. Además, a partir de
    SQLAlchemy 2.1 el esquema ``postgresql://`` selecciona psycopg 3 por
    defecto; el proyecto incluye ``psycopg2-binary``, así que se fija el
    driver explícitamente.
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
    """Configuración base compartida."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-crm-2026")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-crm-2026")

    # Tiempos de expiración de tokens
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Configuración de Base de Datos
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Evita conexiones muertas tras reinicios de PostgreSQL (local o Render).
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # Configuración de CORS
    raw_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173")
    CORS_ORIGINS = [origin.strip() for origin in raw_cors.split(",") if origin.strip()]


class DevelopmentConfig(Config):
    """Configuración para desarrollo local."""

    DEBUG = True
    ENV = "development"


class ProductionConfig(Config):
    """Configuración para entorno de producción."""

    DEBUG = False
    ENV = "production"


class TestingConfig(Config):
    """Configuración para ejecución de pruebas automatizadas."""

    TESTING = True
    # SQLite en memoria por defecto; TEST_DATABASE_URL permite correr la suite
    # contra PostgreSQL sin cambiar el código.
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

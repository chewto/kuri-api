import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuración base compartida."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-crm-2026")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-crm-2026")

    # Tiempos de expiración de tokens
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Configuración de Base de Datos
    raw_database_url = os.getenv("DATABASE_URL", "sqlite:///crm_dev.db")
    # Fix para compatibilidad con SQLAlchemy cuando Render entrega URL postgres://
    if raw_database_url.startswith("postgres://"):
        raw_database_url = raw_database_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = raw_database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

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
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_SECRET_KEY = "test-jwt-secret-key-32-bytes-secure-hash-crm"


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}

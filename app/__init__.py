import os
from flask import Flask, jsonify
from app.config import config_by_name
from app.extensions import db, migrate, jwt, cors
from app.routes.auth import auth_bp
from app.routes.company import company_bp
from app.routes.contact import contact_bp
from app.routes.activity import activity_bp
from app.routes.dashboard import dashboard_bp
from app.routes.category import category_bp
from app.routes.subscription import subscription_bp
from app.routes.transaction import transaction_bp
from app.routes.finance_summary import finance_summary_bp


def create_app(config_name=None):
    """Application Factory para crear y configurar la aplicación Flask."""
    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development")

    app = Flask(__name__)
    config_class = config_by_name.get(config_name, config_by_name["default"])
    app.config.from_object(config_class)

    # Inicializar extensiones
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # Configurar CORS permitiendo orígenes configurados
    cors.init_app(
        app,
        resources={
            r"/api/*": {
                "origins": app.config.get("CORS_ORIGINS", ["*"]),
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            }
        },
        supports_credentials=True,
    )

    # Manejadores de errores personalizados para JWT
    @jwt.unauthorized_loader
    def unauthorized_callback(callback):
        return (
            jsonify(
                {
                    "error": "No autorizado",
                    "message": "Falta el token de autorización en la cabecera.",
                }
            ),
            401,
        )

    @jwt.invalid_token_loader
    def invalid_token_callback(callback):
        return (
            jsonify(
                {
                    "error": "Token inválido",
                    "message": "El token proporcionado no es válido o está malformado.",
                }
            ),
            401,
        )

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return (
            jsonify(
                {
                    "error": "Token expirado",
                    "message": "El token de autenticación ha expirado.",
                }
            ),
            401,
        )

    # Registrar Blueprints
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(company_bp, url_prefix="/api/companies")
    app.register_blueprint(contact_bp, url_prefix="/api/contacts")
    app.register_blueprint(activity_bp, url_prefix="/api/contacts")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(category_bp, url_prefix="/api/finance/categories")
    app.register_blueprint(subscription_bp, url_prefix="/api/finance/subscriptions")
    app.register_blueprint(transaction_bp, url_prefix="/api/finance/transactions")
    app.register_blueprint(finance_summary_bp, url_prefix="/api/finance/summary")

    # Endpoint de Health Check
    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy", "service": "crm-core-api"}), 200

    return app

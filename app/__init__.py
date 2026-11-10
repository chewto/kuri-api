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
from app.routes.stage import stage_bp
from app.routes.deal_forecast import deal_forecast_bp
from app.routes.deal import deal_bp
from app.routes.team import team_bp
from app.routes.analytics import analytics_bp


def create_app(config_name=None):
    """Application factory that creates and configures the Flask application."""
    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development")

    app = Flask(__name__)
    config_class = config_by_name.get(config_name, config_by_name["default"])
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # Configure CORS with the allowed origins
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

    # Custom JWT error handlers
    @jwt.unauthorized_loader
    def unauthorized_callback(callback):
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "message": "Missing authorization token in the request header.",
                }
            ),
            401,
        )

    @jwt.invalid_token_loader
    def invalid_token_callback(callback):
        return (
            jsonify(
                {
                    "error": "Invalid token",
                    "message": "The provided token is invalid or malformed.",
                }
            ),
            401,
        )

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return (
            jsonify(
                {
                    "error": "Token expired",
                    "message": "The authentication token has expired.",
                }
            ),
            401,
        )

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(company_bp, url_prefix="/api/companies")
    app.register_blueprint(contact_bp, url_prefix="/api/contacts")
    app.register_blueprint(activity_bp, url_prefix="/api/contacts")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(category_bp, url_prefix="/api/finance/categories")
    app.register_blueprint(subscription_bp, url_prefix="/api/finance/subscriptions")
    app.register_blueprint(transaction_bp, url_prefix="/api/finance/transactions")
    app.register_blueprint(finance_summary_bp, url_prefix="/api/finance/summary")
    app.register_blueprint(stage_bp, url_prefix="/api/deals/stages")
    app.register_blueprint(deal_forecast_bp, url_prefix="/api/deals/forecast")
    app.register_blueprint(deal_bp, url_prefix="/api/deals")
    app.register_blueprint(team_bp, url_prefix="/api/team")
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")

    # Health check endpoint
    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy", "service": "crm-core-api"}), 200

    return app

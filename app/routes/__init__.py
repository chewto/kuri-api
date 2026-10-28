from app.routes.auth import auth_bp
from app.routes.company import company_bp
from app.routes.contact import contact_bp
from app.routes.activity import activity_bp
from app.routes.dashboard import dashboard_bp
from app.routes.category import category_bp
from app.routes.subscription import subscription_bp
from app.routes.transaction import transaction_bp
from app.routes.finance_summary import finance_summary_bp

__all__ = [
    "auth_bp",
    "company_bp",
    "contact_bp",
    "activity_bp",
    "dashboard_bp",
    "category_bp",
    "subscription_bp",
    "transaction_bp",
    "finance_summary_bp",
]

from flask import Blueprint, jsonify, g
from sqlalchemy import func
from app.extensions import db
from app.models.contact import Contact
from app.models.company import Company
from app.middlewares.tenant_context import tenant_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/stats", methods=["GET"])
@tenant_required
def get_dashboard_stats():
    """Returns the real KPI dashboard counts for the current workspace.

    Pipeline deals and MRR are placeholders (0) until the Deals/Finance module exists.
    """
    try:
        contacts_total = (
            db.session.query(func.count(Contact.id))
            .filter(Contact.tenant_id == g.tenant_id)
            .scalar()
            or 0
        )
        companies_total = (
            db.session.query(func.count(Company.id))
            .filter(Company.tenant_id == g.tenant_id)
            .scalar()
            or 0
        )
    except Exception as exc:
        return (
            jsonify({"error": "Internal error", "message": f"Could not calculate the metrics: {str(exc)}"}),
            500,
        )

    return (
        jsonify(
            {
                "contacts_total": contacts_total,
                "companies_total": companies_total,
                "deals_pipeline_count": 0,
                "deals_pipeline_value": 0.0,
                "mrr_estimated": 0.0,
            }
        ),
        200,
    )

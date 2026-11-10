from flask import Blueprint, jsonify, g
from sqlalchemy import func
from app.extensions import db
from app.models.contact import Contact
from app.models.company import Company
from app.models.deal import Deal
from app.models.subscription import Subscription
from app.middlewares.tenant_context import tenant_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/stats", methods=["GET"])
@tenant_required
def get_dashboard_stats():
    """Returns the real KPI dashboard counts and metrics for the current workspace.

    Includes contacts, registered companies, active deals pipeline value and count,
    won deals (revenue generated), and estimated MRR from active subscriptions.
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

        # Open Deals in Pipeline
        open_deals_stats = (
            db.session.query(
                func.count(Deal.id),
                func.coalesce(func.sum(Deal.value), 0.0),
            )
            .filter(Deal.tenant_id == g.tenant_id, Deal.status == "open")
            .first()
        )
        deals_pipeline_count = open_deals_stats[0] if open_deals_stats else 0
        deals_pipeline_value = float(open_deals_stats[1]) if open_deals_stats else 0.0

        # Won Deals (Revenue Generated)
        won_deals_stats = (
            db.session.query(
                func.count(Deal.id),
                func.coalesce(func.sum(Deal.value), 0.0),
            )
            .filter(Deal.tenant_id == g.tenant_id, Deal.status == "won")
            .first()
        )
        deals_won_count = won_deals_stats[0] if won_deals_stats else 0
        deals_won_value = float(won_deals_stats[1]) if won_deals_stats else 0.0

        # Estimated MRR from active subscriptions
        active_subscriptions = (
            Subscription.query.filter_by(tenant_id=g.tenant_id, status="active").all()
        )
        monthly_mrr = 0.0
        for sub in active_subscriptions:
            cost = float(sub.cost) if sub.cost else 0.0
            if sub.billing_cycle == "monthly":
                monthly_mrr += cost
            elif sub.billing_cycle == "yearly":
                monthly_mrr += cost / 12.0
            elif sub.billing_cycle == "quarterly":
                monthly_mrr += cost / 3.0

        mrr_estimated = round(monthly_mrr, 2)

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
                "deals_pipeline_count": deals_pipeline_count,
                "deals_pipeline_value": round(deals_pipeline_value, 2),
                "deals_won_count": deals_won_count,
                "deals_won_value": round(deals_won_value, 2),
                "mrr_estimated": mrr_estimated,
            }
        ),
        200,
    )

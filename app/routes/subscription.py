from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.subscription import Subscription
from app.models.company import Company
from app.models.category import Category
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

subscription_bp = Blueprint("finance_subscriptions", __name__)

VALID_BILLING_CYCLES = {"monthly", "yearly", "quarterly"}
VALID_STATUSES = {"active", "paused", "cancelled"}


@subscription_bp.route("", methods=["GET"])
@tenant_required
def get_subscriptions():
    """Lists workspace subscriptions with optional filters by status, category_id, and company_id."""
    status = request.args.get("status", "").strip()
    category_id = request.args.get("category_id", "").strip()
    company_id = request.args.get("company_id", "").strip()

    query = Subscription.query.filter_by(tenant_id=g.tenant_id)

    if status:
        if status not in VALID_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": f"Invalid status. Valid options: {', '.join(sorted(VALID_STATUSES))}",
                    }
                ),
                400,
            )
        query = query.filter_by(status=status)

    if category_id:
        query = query.filter_by(category_id=category_id)

    if company_id:
        query = query.filter_by(company_id=company_id)

    subscriptions = query.order_by(Subscription.next_billing_date.asc(), Subscription.created_at.desc()).all()
    return jsonify([sub.to_dict() for sub in subscriptions]), 200


@subscription_bp.route("", methods=["POST"])
@tenant_required
def create_subscription():
    """Creates a new recurring subscription or service (SaaS/OPEX)."""
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    if not name:
        return (
            jsonify({"error": "Validation failed", "message": "The 'name' field is required."}),
            400,
        )

    # Validate cost
    cost_val = data.get("cost")
    if cost_val is None:
        return (
            jsonify({"error": "Validation failed", "message": "The 'cost' field is required."}),
            400,
        )
    try:
        cost = Decimal(str(cost_val))
        if cost < 0:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'cost' field must be a valid decimal number greater than or equal to 0.",
                }
            ),
            400,
        )

    # Validate billing cycle
    billing_cycle = data.get("billing_cycle", "monthly").strip().lower()
    if billing_cycle not in VALID_BILLING_CYCLES:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": f"Invalid billing cycle. Options: {', '.join(sorted(VALID_BILLING_CYCLES))}",
                }
            ),
            400,
        )

    # Validate the next billing date
    next_billing_str = data.get("next_billing_date")
    if not next_billing_str:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'next_billing_date' field (YYYY-MM-DD) is required.",
                }
            ),
            400,
        )
    try:
        next_billing_date = datetime.strptime(str(next_billing_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "Invalid 'next_billing_date' format. Use YYYY-MM-DD.",
                }
            ),
            400,
        )

    # Validate status
    status = data.get("status", "active").strip().lower()
    if status not in VALID_STATUSES:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": f"Invalid status. Options: {', '.join(sorted(VALID_STATUSES))}",
                }
            ),
            400,
        )

    # Validate company_id ownership when provided
    company_id = data.get("company_id")
    if company_id:
        company_id = str(company_id).strip()
        company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
        if not company:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The specified company does not exist in your organization.",
                    }
                ),
                400,
            )
    else:
        company_id = None

    # Validate category_id ownership when provided
    category_id = data.get("category_id")
    if category_id:
        category_id = str(category_id).strip()
        category = Category.query.filter_by(id=category_id, tenant_id=g.tenant_id).first()
        if not category:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The specified category does not exist in your organization.",
                    }
                ),
                400,
            )
    else:
        category_id = None

    subscription = Subscription(
        tenant_id=g.tenant_id,
        company_id=company_id,
        category_id=category_id,
        name=name,
        cost=cost,
        billing_cycle=billing_cycle,
        next_billing_date=next_billing_date,
        status=status,
    )

    try:
        db.session.add(subscription)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Subscription created successfully.",
                    "subscription": subscription.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not create the subscription: {str(exc)}",
                }
            ),
            500,
        )


@subscription_bp.route("/<string:subscription_id>", methods=["PUT"])
@tenant_required
def update_subscription(subscription_id):
    """Updates a subscription's details or changes its status."""
    subscription = Subscription.query.filter_by(id=subscription_id, tenant_id=g.tenant_id).first()
    if not subscription:
        return (
            jsonify(
                {
                    "error": "Not found",
                    "message": "Subscription not found in your organization.",
                }
            ),
            404,
        )

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = str(data["name"]).strip()
        if not name:
            return (
                jsonify({"error": "Validation failed", "message": "The 'name' field cannot be empty."}),
                400,
            )
        subscription.name = name

    if "cost" in data:
        try:
            cost = Decimal(str(data["cost"]))
            if cost < 0:
                raise ValueError
            subscription.cost = cost
        except (InvalidOperation, ValueError, TypeError):
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "The 'cost' field must be a valid decimal number greater than or equal to 0.",
                    }
                ),
                400,
            )

    if "billing_cycle" in data:
        billing_cycle = str(data["billing_cycle"]).strip().lower()
        if billing_cycle not in VALID_BILLING_CYCLES:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": f"Invalid billing cycle. Options: {', '.join(sorted(VALID_BILLING_CYCLES))}",
                    }
                ),
                400,
            )
        subscription.billing_cycle = billing_cycle

    if "next_billing_date" in data:
        try:
            subscription.next_billing_date = datetime.strptime(
                str(data["next_billing_date"]).strip(), "%Y-%m-%d"
            ).date()
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": "Invalid 'next_billing_date' format. Use YYYY-MM-DD.",
                    }
                ),
                400,
            )

    if "status" in data:
        status = str(data["status"]).strip().lower()
        if status not in VALID_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validation failed",
                        "message": f"Invalid status. Options: {', '.join(sorted(VALID_STATUSES))}",
                    }
                ),
                400,
            )
        subscription.status = status

    if "company_id" in data:
        comp_id = data["company_id"]
        if comp_id:
            comp_id = str(comp_id).strip()
            company = Company.query.filter_by(id=comp_id, tenant_id=g.tenant_id).first()
            if not company:
                return (
                    jsonify(
                        {
                            "error": "Validation failed",
                            "message": "The specified company does not exist in your organization.",
                        }
                    ),
                    400,
                )
            subscription.company_id = comp_id
        else:
            subscription.company_id = None

    if "category_id" in data:
        cat_id = data["category_id"]
        if cat_id:
            cat_id = str(cat_id).strip()
            category = Category.query.filter_by(id=cat_id, tenant_id=g.tenant_id).first()
            if not category:
                return (
                    jsonify(
                        {
                            "error": "Validation failed",
                            "message": "The specified category does not exist in your organization.",
                        }
                    ),
                    400,
                )
            subscription.category_id = cat_id
        else:
            subscription.category_id = None

    try:
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Subscription updated successfully.",
                    "subscription": subscription.to_dict(),
                }
            ),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not update the subscription: {str(exc)}",
                }
            ),
            500,
        )


@subscription_bp.route("/<string:subscription_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_subscription(subscription_id):
    """Deletes a subscription while enforcing workspace isolation."""
    subscription = Subscription.query.filter_by(id=subscription_id, tenant_id=g.tenant_id).first()
    if not subscription:
        return (
            jsonify(
                {
                    "error": "Not found",
                    "message": "Subscription not found in your organization.",
                }
            ),
            404,
        )

    try:
        db.session.delete(subscription)
        db.session.commit()
        return jsonify({"message": "Subscription deleted successfully."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not delete the subscription: {str(exc)}",
                }
            ),
            500,
        )

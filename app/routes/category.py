from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.category import Category
from app.middlewares.tenant_context import tenant_required

category_bp = Blueprint("finance_categories", __name__)


@category_bp.route("", methods=["GET"])
@tenant_required
def get_categories():
    """Lists all expense categories in the current workspace, sorted alphabetically."""
    categories = (
        Category.query.filter_by(tenant_id=g.tenant_id)
        .order_by(Category.name.asc())
        .all()
    )
    return jsonify([cat.to_dict() for cat in categories]), 200


@category_bp.route("", methods=["POST"])
@tenant_required
def create_category():
    """Creates a category for classifying workspace expenses and subscriptions."""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()

    if not name:
        return (
            jsonify({"error": "Validation failed", "message": "The 'name' field is required."}),
            400,
        )

    color = data.get("color", "").strip() or "#10B981"

    category = Category(
        tenant_id=g.tenant_id,
        name=name,
        color=color,
    )

    try:
        db.session.add(category)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Category created successfully.",
                    "category": category.to_dict(),
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
                    "message": f"Could not create the category: {str(exc)}",
                }
            ),
            500,
        )

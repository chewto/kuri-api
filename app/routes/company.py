from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.company import Company
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

company_bp = Blueprint("companies", __name__)


@company_bp.route("", methods=["GET"])
@tenant_required
def get_companies():
    """Lists companies in the current workspace with pagination and name search (?search=).

    With ?all=1, pagination is skipped and all companies (max 1000) are returned sorted by name,
    intended for selects and dropdowns.
    """
    search = request.args.get("search", "").strip()
    fetch_all = request.args.get("all", "").strip() in ("1", "true", "True")

    query = Company.query.filter_by(tenant_id=g.tenant_id)

    if search:
        query = query.filter(Company.name.ilike(f"%{search}%"))

    if fetch_all:
        companies = query.order_by(Company.name.asc()).limit(1000).all()
        items = [company.to_dict() for company in companies]
        return (
            jsonify(
                {
                    "items": items,
                    "total": len(items),
                    "page": 1,
                    "per_page": len(items),
                    "pages": 1,
                }
            ),
            200,
        )

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        page = 1
        per_page = 20

    query = query.order_by(Company.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return (
        jsonify(
            {
                "items": [company.to_dict() for company in pagination.items],
                "total": pagination.total,
                "page": pagination.page,
                "per_page": pagination.per_page,
                "pages": pagination.pages,
            }
        ),
        200,
    )


@company_bp.route("", methods=["POST"])
@tenant_required
def create_company():
    """Creates a company associated with the current workspace."""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()

    if not name:
        return (
            jsonify({"error": "Validation failed", "message": "The 'name' field is required."}),
            400,
        )

    company = Company(
        tenant_id=g.tenant_id,
        name=name,
        tax_id=data.get("tax_id", "").strip() or None,
        industry=data.get("industry", "").strip() or None,
        website=data.get("website", "").strip() or None,
        phone=data.get("phone", "").strip() or None,
        address=data.get("address", "").strip() or None,
    )

    try:
        db.session.add(company)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Company created successfully.",
                    "company": company.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not create the company: {str(exc)}"}),
            500,
        )


@company_bp.route("/<string:company_id>", methods=["GET"])
@tenant_required
def get_company(company_id):
    """Returns a company's details together with its associated contacts."""
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify({"error": "Not found", "message": "Company not found in your organization."}),
            404,
        )

    return jsonify({"company": company.to_dict(include_contacts=True)}), 200


@company_bp.route("/<string:company_id>", methods=["PUT"])
@tenant_required
def update_company(company_id):
    """Updates the company's details."""
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify({"error": "Not found", "message": "Company not found in your organization."}),
            404,
        )

    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if name is not None:
        name = name.strip()
        if not name:
            return (
                jsonify({"error": "Validation failed", "message": "The 'name' field cannot be empty."}),
                400,
            )
        company.name = name

    if "tax_id" in data:
        company.tax_id = data["tax_id"].strip() if isinstance(data["tax_id"], str) else None
    if "industry" in data:
        company.industry = data["industry"].strip() if isinstance(data["industry"], str) else None
    if "website" in data:
        company.website = data["website"].strip() if isinstance(data["website"], str) else None
    if "phone" in data:
        company.phone = data["phone"].strip() if isinstance(data["phone"], str) else None
    if "address" in data:
        company.address = data["address"].strip() if isinstance(data["address"], str) else None

    try:
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Company updated successfully.",
                    "company": company.to_dict(),
                }
            ),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not update the company: {str(exc)}"}),
            500,
        )


@company_bp.route("/<string:company_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_company(company_id):
    """Deletes the company while enforcing workspace isolation."""
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify({"error": "Not found", "message": "Company not found in your organization."}),
            404,
        )

    try:
        db.session.delete(company)
        db.session.commit()
        return jsonify({"message": "Company deleted successfully."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not delete the company: {str(exc)}"}),
            500,
        )

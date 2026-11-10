from flask import Blueprint, request, jsonify, g
from sqlalchemy import or_
from app.extensions import db
from app.models.contact import Contact
from app.models.company import Company
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

contact_bp = Blueprint("contacts", __name__)


@contact_bp.route("", methods=["GET"])
@tenant_required
def get_contacts():
    """Lists contacts in the current workspace with name/email search and company_id filtering."""
    search = request.args.get("search", "").strip()
    company_id = request.args.get("company_id", "").strip()

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        page = 1
        per_page = 20

    query = Contact.query.filter_by(tenant_id=g.tenant_id)

    if company_id:
        query = query.filter(Contact.company_id == company_id)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                Contact.first_name.ilike(search_filter),
                Contact.last_name.ilike(search_filter),
                Contact.email.ilike(search_filter),
            )
        )

    query = query.order_by(Contact.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return (
        jsonify(
            {
                "items": [contact.to_dict() for contact in pagination.items],
                "total": pagination.total,
                "page": pagination.page,
                "per_page": pagination.per_page,
                "pages": pagination.pages,
            }
        ),
        200,
    )


@contact_bp.route("", methods=["POST"])
@tenant_required
def create_contact():
    """Creates a contact associated with the current workspace."""
    data = request.get_json(silent=True) or {}
    first_name = data.get("first_name", "").strip()

    if not first_name:
        return (
            jsonify({"error": "Validation failed", "message": "The 'first_name' field is required."}),
            400,
        )

    company_id = data.get("company_id")
    if company_id:
        company_id = company_id.strip()
        # Verify that the company exists and belongs to the same workspace
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

    contact = Contact(
        tenant_id=g.tenant_id,
        company_id=company_id,
        first_name=first_name,
        last_name=data.get("last_name", "").strip() or None,
        email=data.get("email", "").strip().lower() or None,
        phone=data.get("phone", "").strip() or None,
        position=data.get("position", "").strip() or None,
    )

    try:
        db.session.add(contact)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Contact created successfully.",
                    "contact": contact.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not create the contact: {str(exc)}"}),
            500,
        )


@contact_bp.route("/<string:contact_id>", methods=["GET"])
@tenant_required
def get_contact(contact_id):
    """Returns the contact's details."""
    contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
    if not contact:
        return (
            jsonify({"error": "Not found", "message": "Contact not found in your organization."}),
            404,
        )

    return jsonify({"contact": contact.to_dict()}), 200


@contact_bp.route("/<string:contact_id>", methods=["PUT"])
@tenant_required
def update_contact(contact_id):
    """Updates the contact's details."""
    contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
    if not contact:
        return (
            jsonify({"error": "Not found", "message": "Contact not found in your organization."}),
            404,
        )

    data = request.get_json(silent=True) or {}
    first_name = data.get("first_name")
    if first_name is not None:
        first_name = first_name.strip()
        if not first_name:
            return (
                jsonify({"error": "Validation failed", "message": "The 'first_name' field cannot be empty."}),
                400,
            )
        contact.first_name = first_name

    if "company_id" in data:
        new_company_id = data["company_id"]
        if new_company_id:
            new_company_id = str(new_company_id).strip()
            # Verify that the new company belongs to the same workspace
            company = Company.query.filter_by(id=new_company_id, tenant_id=g.tenant_id).first()
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
            contact.company_id = new_company_id
        else:
            contact.company_id = None

    if "last_name" in data:
        contact.last_name = data["last_name"].strip() if isinstance(data["last_name"], str) else None
    if "email" in data:
        contact.email = data["email"].strip().lower() if isinstance(data["email"], str) else None
    if "phone" in data:
        contact.phone = data["phone"].strip() if isinstance(data["phone"], str) else None
    if "position" in data:
        contact.position = data["position"].strip() if isinstance(data["position"], str) else None

    try:
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Contact updated successfully.",
                    "contact": contact.to_dict(),
                }
            ),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not update the contact: {str(exc)}"}),
            500,
        )


@contact_bp.route("/<string:contact_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_contact(contact_id):
    """Deletes the contact while enforcing workspace isolation."""
    contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
    if not contact:
        return (
            jsonify({"error": "Not found", "message": "Contact not found in your organization."}),
            404,
        )

    try:
        db.session.delete(contact)
        db.session.commit()
        return jsonify({"message": "Contact deleted successfully."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not delete the contact: {str(exc)}"}),
            500,
        )

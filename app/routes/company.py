from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.company import Company
from app.middlewares.tenant_context import tenant_required

company_bp = Blueprint("companies", __name__)


@company_bp.route("", methods=["GET"])
@tenant_required
def get_companies():
    """Lista empresas del tenant_id actual con paginación y filtro de búsqueda por nombre (?search=).

    Con ?all=1 se omita la paginación y se devuelven todas (máx. 1000) ordenadas por nombre,
    pensado para selects/dropdowns.
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
    """Crea una empresa asociada al tenant_id en sesión."""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()

    if not name:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'name' es requerido."}),
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
                    "message": "Empresa creada exitosamente.",
                    "company": company.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Error interno", "message": f"No se pudo crear la empresa: {str(exc)}"}),
            500,
        )


@company_bp.route("/<string:company_id>", methods=["GET"])
@tenant_required
def get_company(company_id):
    """Obtiene el detalle de una empresa con sus contactos asociados."""
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify({"error": "No encontrado", "message": "Empresa no encontrada en su organización."}),
            404,
        )

    return jsonify({"company": company.to_dict(include_contacts=True)}), 200


@company_bp.route("/<string:company_id>", methods=["PUT"])
@tenant_required
def update_company(company_id):
    """Actualiza los datos de la empresa."""
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify({"error": "No encontrado", "message": "Empresa no encontrada en su organización."}),
            404,
        )

    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if name is not None:
        name = name.strip()
        if not name:
            return (
                jsonify({"error": "Validación fallida", "message": "El campo 'name' no puede estar vacío."}),
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
                    "message": "Empresa actualizada exitosamente.",
                    "company": company.to_dict(),
                }
            ),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Error interno", "message": f"No se pudo actualizar la empresa: {str(exc)}"}),
            500,
        )


@company_bp.route("/<string:company_id>", methods=["DELETE"])
@tenant_required
def delete_company(company_id):
    """Elimina la empresa asegurando aislamiento de Tenant."""
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify({"error": "No encontrado", "message": "Empresa no encontrada en su organización."}),
            404,
        )

    try:
        db.session.delete(company)
        db.session.commit()
        return jsonify({"message": "Empresa eliminada exitosamente."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Error interno", "message": f"No se pudo eliminar la empresa: {str(exc)}"}),
            500,
        )

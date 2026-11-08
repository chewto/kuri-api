from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.transaction import Transaction
from app.models.company import Company
from app.models.category import Category
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

transaction_bp = Blueprint("finance_transactions", __name__)

VALID_TRANSACTION_TYPES = {"income", "expense"}


@transaction_bp.route("", methods=["GET"])
@tenant_required
def get_transactions():
    """Lista transacciones con filtros por type, rango de fechas (start_date, end_date), category_id, company_id y paginación."""
    tx_type = request.args.get("type", "").strip().lower()
    start_date_str = request.args.get("start_date", "").strip()
    end_date_str = request.args.get("end_date", "").strip()
    category_id = request.args.get("category_id", "").strip()
    company_id = request.args.get("company_id", "").strip()
    fetch_all = request.args.get("all", "").strip() in ("1", "true", "True")

    query = Transaction.query.filter_by(tenant_id=g.tenant_id)

    if tx_type:
        if tx_type not in VALID_TRANSACTION_TYPES:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": f"Tipo inválido. Opciones: {', '.join(sorted(VALID_TRANSACTION_TYPES))}",
                    }
                ),
                400,
            )
        query = query.filter_by(type=tx_type)

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            query = query.filter(Transaction.date >= start_date)
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "Formato de 'start_date' inválido. Use YYYY-MM-DD.",
                    }
                ),
                400,
            )

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            query = query.filter(Transaction.date <= end_date)
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "Formato de 'end_date' inválido. Use YYYY-MM-DD.",
                    }
                ),
                400,
            )

    if category_id:
        query = query.filter_by(category_id=category_id)

    if company_id:
        query = query.filter_by(company_id=company_id)

    query = query.order_by(Transaction.date.desc(), Transaction.created_at.desc())

    if fetch_all:
        transactions = query.limit(2000).all()
        items = [tx.to_dict() for tx in transactions]
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

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return (
        jsonify(
            {
                "items": [tx.to_dict() for tx in pagination.items],
                "total": pagination.total,
                "page": pagination.page,
                "per_page": pagination.per_page,
                "pages": pagination.pages,
            }
        ),
        200,
    )


@transaction_bp.route("", methods=["POST"])
@tenant_required
def create_transaction():
    """Registra un nuevo movimiento de caja (ingreso o egreso)."""
    data = request.get_json(silent=True) or {}

    tx_type = str(data.get("type", "")).strip().lower()
    if tx_type not in VALID_TRANSACTION_TYPES:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": f"El campo 'type' es requerido ({', '.join(sorted(VALID_TRANSACTION_TYPES))}).",
                }
            ),
            400,
        )

    amount_val = data.get("amount")
    if amount_val is None:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'amount' es requerido."}),
            400,
        )
    try:
        amount = Decimal(str(amount_val))
        if amount <= 0:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El campo 'amount' debe ser un número decimal mayor a 0.",
                }
            ),
            400,
        )

    description = data.get("description", "").strip()
    if not description:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'description' es requerido."}),
            400,
        )

    date_str = data.get("date")
    if not date_str:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'date' (YYYY-MM-DD) es requerido."}),
            400,
        )
    try:
        tx_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "Formato de 'date' inválido. Use YYYY-MM-DD.",
                }
            ),
            400,
        )

    # Validar categoría si se proporciona
    category_id = data.get("category_id")
    if category_id:
        category_id = str(category_id).strip()
        category = Category.query.filter_by(id=category_id, tenant_id=g.tenant_id).first()
        if not category:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "La categoría especificada no existe en su organización.",
                    }
                ),
                400,
            )
    else:
        category_id = None

    # Validar empresa/cliente si se proporciona
    company_id = data.get("company_id")
    if company_id:
        company_id = str(company_id).strip()
        company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
        if not company:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "La empresa especificada no existe en su organización.",
                    }
                ),
                400,
            )
    else:
        company_id = None

    transaction = Transaction(
        tenant_id=g.tenant_id,
        category_id=category_id,
        company_id=company_id,
        type=tx_type,
        amount=amount,
        description=description,
        date=tx_date,
    )

    try:
        db.session.add(transaction)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Transacción registrada exitosamente.",
                    "transaction": transaction.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Error interno",
                    "message": f"No se pudo registrar la transacción: {str(exc)}",
                }
            ),
            500,
        )


@transaction_bp.route("/<string:transaction_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_transaction(transaction_id):
    """Elimina una transacción garantizando aislamiento de Tenant."""
    transaction = Transaction.query.filter_by(id=transaction_id, tenant_id=g.tenant_id).first()
    if not transaction:
        return (
            jsonify(
                {
                    "error": "No encontrado",
                    "message": "Transacción no encontrada en su organización.",
                }
            ),
            404,
        )

    try:
        db.session.delete(transaction)
        db.session.commit()
        return jsonify({"message": "Transacción eliminada exitosamente."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Error interno",
                    "message": f"No se pudo eliminar la transacción: {str(exc)}",
                }
            ),
            500,
        )

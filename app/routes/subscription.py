from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.subscription import Subscription
from app.models.company import Company
from app.models.category import Category
from app.middlewares.tenant_context import tenant_required

subscription_bp = Blueprint("finance_subscriptions", __name__)

VALID_BILLING_CYCLES = {"monthly", "yearly", "quarterly"}
VALID_STATUSES = {"active", "paused", "cancelled"}


@subscription_bp.route("", methods=["GET"])
@tenant_required
def get_subscriptions():
    """Lista suscripciones del tenant con filtros opcionales por status, category_id y company_id."""
    status = request.args.get("status", "").strip()
    category_id = request.args.get("category_id", "").strip()
    company_id = request.args.get("company_id", "").strip()

    query = Subscription.query.filter_by(tenant_id=g.tenant_id)

    if status:
        if status not in VALID_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": f"Estado inválido. Opciones válidas: {', '.join(sorted(VALID_STATUSES))}",
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
    """Registra una nueva suscripción/servicio recurrente (SaaS/OPEX)."""
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    if not name:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'name' es requerido."}),
            400,
        )

    # Validar costo
    cost_val = data.get("cost")
    if cost_val is None:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'cost' es requerido."}),
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
                    "error": "Validación fallida",
                    "message": "El campo 'cost' debe ser un número decimal válido mayor o igual a 0.",
                }
            ),
            400,
        )

    # Validar ciclo de facturación
    billing_cycle = data.get("billing_cycle", "monthly").strip().lower()
    if billing_cycle not in VALID_BILLING_CYCLES:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": f"Ciclo de facturación inválido. Opciones: {', '.join(sorted(VALID_BILLING_CYCLES))}",
                }
            ),
            400,
        )

    # Validar fecha próximo cobro
    next_billing_str = data.get("next_billing_date")
    if not next_billing_str:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El campo 'next_billing_date' (YYYY-MM-DD) es requerido.",
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
                    "error": "Validación fallida",
                    "message": "Formato de 'next_billing_date' inválido. Use YYYY-MM-DD.",
                }
            ),
            400,
        )

    # Validar status
    status = data.get("status", "active").strip().lower()
    if status not in VALID_STATUSES:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": f"Estado inválido. Opciones: {', '.join(sorted(VALID_STATUSES))}",
                }
            ),
            400,
        )

    # Validar pertenencia de company_id si fue provisto
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

    # Validar pertenencia de category_id si fue provisto
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
                    "message": "Suscripción registrada exitosamente.",
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
                    "error": "Error interno",
                    "message": f"No se pudo registrar la suscripción: {str(exc)}",
                }
            ),
            500,
        )


@subscription_bp.route("/<string:subscription_id>", methods=["PUT"])
@tenant_required
def update_subscription(subscription_id):
    """Actualiza los datos o cambia el estado de una suscripción."""
    subscription = Subscription.query.filter_by(id=subscription_id, tenant_id=g.tenant_id).first()
    if not subscription:
        return (
            jsonify(
                {
                    "error": "No encontrado",
                    "message": "Suscripción no encontrada en su organización.",
                }
            ),
            404,
        )

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = str(data["name"]).strip()
        if not name:
            return (
                jsonify({"error": "Validación fallida", "message": "El campo 'name' no puede estar vacío."}),
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
                        "error": "Validación fallida",
                        "message": "El campo 'cost' debe ser un número decimal válido mayor o igual a 0.",
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
                        "error": "Validación fallida",
                        "message": f"Ciclo de facturación inválido. Opciones: {', '.join(sorted(VALID_BILLING_CYCLES))}",
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
                        "error": "Validación fallida",
                        "message": "Formato de 'next_billing_date' inválido. Use YYYY-MM-DD.",
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
                        "error": "Validación fallida",
                        "message": f"Estado inválido. Opciones: {', '.join(sorted(VALID_STATUSES))}",
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
                            "error": "Validación fallida",
                            "message": "La empresa especificada no existe en su organización.",
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
                            "error": "Validación fallida",
                            "message": "La categoría especificada no existe en su organización.",
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
                    "message": "Suscripción actualizada exitosamente.",
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
                    "error": "Error interno",
                    "message": f"No se pudo actualizar la suscripción: {str(exc)}",
                }
            ),
            500,
        )


@subscription_bp.route("/<string:subscription_id>", methods=["DELETE"])
@tenant_required
def delete_subscription(subscription_id):
    """Elimina una suscripción garantizando aislamiento de Tenant."""
    subscription = Subscription.query.filter_by(id=subscription_id, tenant_id=g.tenant_id).first()
    if not subscription:
        return (
            jsonify(
                {
                    "error": "No encontrado",
                    "message": "Suscripción no encontrada en su organización.",
                }
            ),
            404,
        )

    try:
        db.session.delete(subscription)
        db.session.commit()
        return jsonify({"message": "Suscripción eliminada exitosamente."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Error interno",
                    "message": f"No se pudo eliminar la suscripción: {str(exc)}",
                }
            ),
            500,
        )

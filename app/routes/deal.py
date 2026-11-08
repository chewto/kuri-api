from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.deal import Deal
from app.models.stage import Stage
from app.models.company import Company
from app.models.contact import Contact
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

deal_bp = Blueprint("deals", __name__)

VALID_DEAL_STATUSES = {"open", "won", "lost"}


@deal_bp.route("", methods=["GET"])
@tenant_required
def get_deals():
    """Lista las oportunidades de negocio del tenant con filtros opcionales.

    Soporta filtros por stage_id, status, company_id, contact_id, búsqueda por título (?search=),
    agrupación por etapas para vistas Kanban (?grouped=true) y paginación.
    """
    stage_id = request.args.get("stage_id", "").strip()
    status = request.args.get("status", "").strip().lower()
    company_id = request.args.get("company_id", "").strip()
    contact_id = request.args.get("contact_id", "").strip()
    search = request.args.get("search", "").strip()
    grouped = request.args.get("grouped", "").strip() in ("1", "true", "True")
    fetch_all = request.args.get("all", "").strip() in ("1", "true", "True")

    # Si se solicita agrupado para la vista Kanban
    if grouped:
        stages = (
            Stage.query.filter_by(tenant_id=g.tenant_id)
            .order_by(Stage.order.asc())
            .all()
        )
        # Consultar todos los tratos del tenant
        deals_query = Deal.query.filter_by(tenant_id=g.tenant_id)
        if status:
            if status in VALID_DEAL_STATUSES:
                deals_query = deals_query.filter_by(status=status)
        if company_id:
            deals_query = deals_query.filter_by(company_id=company_id)
        if search:
            deals_query = deals_query.filter(Deal.title.ilike(f"%{search}%"))

        deals = deals_query.order_by(Deal.created_at.desc()).all()

        deals_by_stage = {}
        for d in deals:
            deals_by_stage.setdefault(d.stage_id, []).append(d.to_dict())

        grouped_stages = []
        for stage in stages:
            stage_dict = stage.to_dict()
            stage_dict["deals"] = deals_by_stage.get(stage.id, [])
            stage_dict["total_deals"] = len(stage_dict["deals"])
            stage_dict["total_value"] = sum(d["value"] for d in stage_dict["deals"])
            grouped_stages.append(stage_dict)

        return jsonify({"stages": grouped_stages}), 200

    query = Deal.query.filter_by(tenant_id=g.tenant_id)

    if stage_id:
        query = query.filter_by(stage_id=stage_id)

    if status:
        if status not in VALID_DEAL_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": f"Estado inválido. Opciones: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                    }
                ),
                400,
            )
        query = query.filter_by(status=status)

    if company_id:
        query = query.filter_by(company_id=company_id)

    if contact_id:
        query = query.filter_by(contact_id=contact_id)

    if search:
        query = query.filter(Deal.title.ilike(f"%{search}%"))

    query = query.order_by(Deal.created_at.desc())

    if fetch_all:
        deals = query.limit(2000).all()
        items = [deal.to_dict() for deal in deals]
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
                "items": [d.to_dict() for d in pagination.items],
                "total": pagination.total,
                "page": pagination.page,
                "per_page": pagination.per_page,
                "pages": pagination.pages,
            }
        ),
        200,
    )


@deal_bp.route("/<deal_id>", methods=["GET"])
@tenant_required
def get_deal(deal_id):
    """Obtiene el detalle de un trato perteneciente al tenant."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "No encontrado", "message": "El trato solicitado no existe."}),
            404,
        )
    return jsonify(deal.to_dict()), 200


@deal_bp.route("", methods=["POST"])
@tenant_required
def create_deal():
    """Registra una nueva oportunidad de venta asociada a una Empresa y Contacto."""
    data = request.get_json(silent=True) or {}

    title = str(data.get("title", "")).strip()
    if not title:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'title' es requerido."}),
            400,
        )

    company_id = str(data.get("company_id", "")).strip()
    if not company_id:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'company_id' es requerido."}),
            400,
        )

    # Validar que la empresa pertenezca al tenant
    company = Company.query.filter_by(id=company_id, tenant_id=g.tenant_id).first()
    if not company:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "La empresa especificada no existe o no pertenece a su organización.",
                }
            ),
            400,
        )

    stage_id = str(data.get("stage_id", "")).strip()
    if not stage_id:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'stage_id' es requerido."}),
            400,
        )

    # Validar que la etapa pertenezca al tenant
    stage = Stage.query.filter_by(id=stage_id, tenant_id=g.tenant_id).first()
    if not stage:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "La etapa especificada no existe o no pertenece a su organización.",
                }
            ),
            400,
        )

    # Validar contacto opcional
    contact_id = data.get("contact_id")
    if contact_id:
        contact_id = str(contact_id).strip()
        contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
        if not contact:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "El contacto especificado no existe o no pertenece a su organización.",
                    }
                ),
                400,
            )
    else:
        contact_id = None

    # Validar monto value
    value_raw = data.get("value")
    if value_raw is None:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'value' es requerido."}),
            400,
        )
    try:
        deal_value = Decimal(str(value_raw))
        if deal_value < Decimal("0.00"):
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El campo 'value' debe ser un número decimal mayor o igual a 0.",
                }
            ),
            400,
        )

    # Validar status
    status = str(data.get("status", "open")).strip().lower()
    if status not in VALID_DEAL_STATUSES:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": f"Estado inválido. Opciones: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                }
            ),
            400,
        )

    # Validar expected_close_date
    expected_close_date = None
    date_str = data.get("expected_close_date")
    if date_str:
        try:
            expected_close_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "Formato de 'expected_close_date' inválido. Use YYYY-MM-DD.",
                    }
                ),
                400,
            )

    deal = Deal(
        tenant_id=g.tenant_id,
        company_id=company_id,
        contact_id=contact_id,
        stage_id=stage_id,
        title=title,
        value=deal_value,
        expected_close_date=expected_close_date,
        status=status,
    )

    try:
        db.session.add(deal)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Oportunidad de negocio creada exitosamente.",
                    "deal": deal.to_dict(),
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
                    "message": f"No se pudo crear la oportunidad de negocio: {str(exc)}",
                }
            ),
            500,
        )


@deal_bp.route("/<deal_id>", methods=["PUT"])
@tenant_required
def update_deal(deal_id):
    """Actualiza la información completa de una oportunidad de venta."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "No encontrado", "message": "El trato solicitado no existe."}),
            404,
        )

    data = request.get_json(silent=True) or {}

    if "title" in data:
        title = str(data["title"]).strip()
        if not title:
            return (
                jsonify({"error": "Validación fallida", "message": "El campo 'title' no puede estar vacío."}),
                400,
            )
        deal.title = title

    if "company_id" in data:
        cid = str(data["company_id"]).strip()
        company = Company.query.filter_by(id=cid, tenant_id=g.tenant_id).first()
        if not company:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "La empresa especificada no existe o no pertenece a su organización.",
                    }
                ),
                400,
            )
        deal.company_id = cid

    if "stage_id" in data:
        sid = str(data["stage_id"]).strip()
        stage = Stage.query.filter_by(id=sid, tenant_id=g.tenant_id).first()
        if not stage:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "La etapa especificada no existe o no pertenece a su organización.",
                    }
                ),
                400,
            )
        deal.stage_id = sid

    if "contact_id" in data:
        ctid = data["contact_id"]
        if ctid:
            ctid = str(ctid).strip()
            contact = Contact.query.filter_by(id=ctid, tenant_id=g.tenant_id).first()
            if not contact:
                return (
                    jsonify(
                        {
                            "error": "Validación fallida",
                            "message": "El contacto especificado no existe o no pertenece a su organización.",
                        }
                    ),
                    400,
                )
            deal.contact_id = ctid
        else:
            deal.contact_id = None

    if "value" in data:
        try:
            val = Decimal(str(data["value"]))
            if val < Decimal("0.00"):
                raise ValueError()
            deal.value = val
        except (InvalidOperation, ValueError, TypeError):
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "El campo 'value' debe ser un número decimal mayor o igual a 0.",
                    }
                ),
                400,
            )

    if "status" in data:
        st = str(data["status"]).strip().lower()
        if st not in VALID_DEAL_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": f"Estado inválido. Opciones: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                    }
                ),
                400,
            )
        deal.status = st

    if "expected_close_date" in data:
        date_str = data["expected_close_date"]
        if date_str:
            try:
                deal.expected_close_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
            except ValueError:
                return (
                    jsonify(
                        {
                            "error": "Validación fallida",
                            "message": "Formato de 'expected_close_date' inválido. Use YYYY-MM-DD.",
                        }
                    ),
                    400,
                )
        else:
            deal.expected_close_date = None

    try:
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Oportunidad de negocio actualizada exitosamente.",
                    "deal": deal.to_dict(),
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
                    "message": f"No se pudo actualizar el trato: {str(exc)}",
                }
            ),
            500,
        )


@deal_bp.route("/<deal_id>/move", methods=["PATCH"])
@tenant_required
def move_deal(deal_id):
    """Endpoint optimizado para mover un trato de etapa (stage_id) o cambiar su status (drag & drop Kanban)."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "No encontrado", "message": "El trato solicitado no existe."}),
            404,
        )

    data = request.get_json(silent=True) or {}
    new_stage_id = data.get("stage_id")
    new_status = data.get("status")

    if not new_stage_id and not new_status:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "Debe especificar al menos 'stage_id' o 'status' para mover el trato.",
                }
            ),
            400,
        )

    if new_stage_id:
        new_stage_id = str(new_stage_id).strip()
        stage = Stage.query.filter_by(id=new_stage_id, tenant_id=g.tenant_id).first()
        if not stage:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": "La etapa de destino no existe o no pertenece a su organización.",
                    }
                ),
                400,
            )
        deal.stage_id = new_stage_id

        # Comportamiento inteligente si no se pasó status explícito:
        if not new_status:
            normalized_name = stage.name.lower()
            if "ganado" in normalized_name or "won" in normalized_name:
                deal.status = "won"
            elif "perdido" in normalized_name or "lost" in normalized_name:
                deal.status = "lost"
            elif deal.status in ("won", "lost"):
                # Si regresa a una etapa intermedia de embudo
                deal.status = "open"

    if new_status:
        st = str(new_status).strip().lower()
        if st not in VALID_DEAL_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Validación fallida",
                        "message": f"Estado inválido. Opciones: {', '.join(sorted(VALID_DEAL_STATUSES))}",
                    }
                ),
                400,
            )
        deal.status = st

    try:
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Trato movido exitosamente.",
                    "deal": deal.to_dict(),
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
                    "message": f"No se pudo mover el trato: {str(exc)}",
                }
            ),
            500,
        )


@deal_bp.route("/<deal_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_deal(deal_id):
    """Elimina una oportunidad de venta."""
    deal = Deal.query.filter_by(id=deal_id, tenant_id=g.tenant_id).first()
    if not deal:
        return (
            jsonify({"error": "No encontrado", "message": "El trato solicitado no existe."}),
            404,
        )

    try:
        db.session.delete(deal)
        db.session.commit()
        return jsonify({"message": "Oportunidad de negocio eliminada exitosamente."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Error interno",
                    "message": f"No se pudo eliminar el trato: {str(exc)}",
                }
            ),
            500,
        )

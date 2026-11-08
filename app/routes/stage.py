from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.stage import Stage, DEFAULT_STAGES
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

stage_bp = Blueprint("stages", __name__)


def _seed_default_stages(tenant_id: str):
    """Inicializa las etapas comerciales por defecto para el tenant si no existen."""
    stages = []
    for item in DEFAULT_STAGES:
        stage = Stage(
            tenant_id=tenant_id,
            name=item["name"],
            order=item["order"],
            probability=item["probability"],
        )
        db.session.add(stage)
        stages.append(stage)
    db.session.commit()
    return stages


@stage_bp.route("", methods=["GET"])
@tenant_required
def get_stages():
    """Lista las etapas del embudo de ventas del tenant ordenadas por la columna order.

    Si el tenant no tiene etapas creadas, se auto-inicializan las etapas por defecto.
    """
    stages = (
        Stage.query.filter_by(tenant_id=g.tenant_id)
        .order_by(Stage.order.asc())
        .all()
    )

    if not stages:
        stages = _seed_default_stages(g.tenant_id)

    return jsonify([stage.to_dict() for stage in stages]), 200


@stage_bp.route("", methods=["POST"])
@tenant_required
def create_stage():
    """Crea una etapa personalizada o inicializa las etapas estándar del tenant."""
    data = request.get_json(silent=True) or {}

    # Si se solicita inicializar por defecto
    if data.get("init_defaults") is True:
        existing = Stage.query.filter_by(tenant_id=g.tenant_id).count()
        if existing == 0:
            stages = _seed_default_stages(g.tenant_id)
            return (
                jsonify(
                    {
                        "message": "Etapas estándar inicializadas exitosamente.",
                        "stages": [s.to_dict() for s in stages],
                    }
                ),
                201,
            )
        stages = Stage.query.filter_by(tenant_id=g.tenant_id).order_by(Stage.order.asc()).all()
        return (
            jsonify(
                {
                    "message": "El tenant ya cuenta con etapas configuradas.",
                    "stages": [s.to_dict() for s in stages],
                }
            ),
            200,
        )

    name = data.get("name", "").strip()
    if not name:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'name' es requerido."}),
            400,
        )

    # Validar orden
    try:
        order = int(data.get("order", 1))
    except (ValueError, TypeError):
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'order' debe ser un número entero."}),
            400,
        )

    # Validar probabilidad (0 - 100)
    try:
        probability = int(data.get("probability", 100))
        if probability < 0 or probability > 100:
            raise ValueError()
    except (ValueError, TypeError):
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El campo 'probability' debe ser un entero entre 0 y 100.",
                }
            ),
            400,
        )

    stage = Stage(
        tenant_id=g.tenant_id,
        name=name,
        order=order,
        probability=probability,
    )

    try:
        db.session.add(stage)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Etapa creada exitosamente.",
                    "stage": stage.to_dict(),
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
                    "message": f"No se pudo crear la etapa: {str(exc)}",
                }
            ),
            500,
        )


@stage_bp.route("/<stage_id>", methods=["PUT"])
@tenant_required
def update_stage(stage_id):
    """Actualiza una etapa existente del tenant."""
    stage = Stage.query.filter_by(id=stage_id, tenant_id=g.tenant_id).first()
    if not stage:
        return (
            jsonify({"error": "No encontrado", "message": "La etapa solicitada no existe."}),
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
        stage.name = name

    if "order" in data:
        try:
            stage.order = int(data["order"])
        except (ValueError, TypeError):
            return (
                jsonify({"error": "Validación fallida", "message": "El campo 'order' debe ser entero."}),
                400,
            )

    if "probability" in data:
        try:
            prob = int(data["probability"])
            if prob < 0 or prob > 100:
                raise ValueError()
            stage.probability = prob
        except (ValueError, TypeError):
            return (
                jsonify({"error": "Validación fallida", "message": "El campo 'probability' debe ser entre 0 y 100."}),
                400,
            )

    try:
        db.session.commit()
        return (
            jsonify({"message": "Etapa actualizada exitosamente.", "stage": stage.to_dict()}),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Error interno", "message": f"No se pudo actualizar la etapa: {str(exc)}"}),
            500,
        )


@stage_bp.route("/<stage_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_stage(stage_id):
    """Elimina una etapa si no contiene tratos vinculados."""
    stage = Stage.query.filter_by(id=stage_id, tenant_id=g.tenant_id).first()
    if not stage:
        return (
            jsonify({"error": "No encontrado", "message": "La etapa solicitada no existe."}),
            404,
        )

    if stage.deals.count() > 0:
        return (
            jsonify(
                {
                    "error": "Operación no permitida",
                    "message": "No se puede eliminar una etapa con oportunidades de negocio asociadas. Muévalas antes.",
                }
            ),
            409,
        )

    try:
        db.session.delete(stage)
        db.session.commit()
        return jsonify({"message": "Etapa eliminada exitosamente."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Error interno", "message": f"No se pudo eliminar la etapa: {str(exc)}"}),
            500,
        )

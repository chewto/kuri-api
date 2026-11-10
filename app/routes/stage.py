from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.stage import Stage, DEFAULT_STAGES
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

stage_bp = Blueprint("stages", __name__)


def _seed_default_stages(tenant_id: str):
    """Initializes the default sales stages for the workspace when none exist."""
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
    """Lists the workspace sales pipeline stages ordered by the order column.

    If the workspace has no stages, the default stages are initialized automatically.
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
    """Creates a custom stage or initializes the workspace's standard stages."""
    data = request.get_json(silent=True) or {}

    # If default initialization is requested
    if data.get("init_defaults") is True:
        existing = Stage.query.filter_by(tenant_id=g.tenant_id).count()
        if existing == 0:
            stages = _seed_default_stages(g.tenant_id)
            return (
                jsonify(
                    {
                        "message": "Default stages initialized successfully.",
                        "stages": [s.to_dict() for s in stages],
                    }
                ),
                201,
            )
        stages = Stage.query.filter_by(tenant_id=g.tenant_id).order_by(Stage.order.asc()).all()
        return (
            jsonify(
                {
                    "message": "This workspace already has stages configured.",
                    "stages": [s.to_dict() for s in stages],
                }
            ),
            200,
        )

    name = data.get("name", "").strip()
    if not name:
        return (
            jsonify({"error": "Validation failed", "message": "The 'name' field is required."}),
            400,
        )

    # Validate order
    try:
        order = int(data.get("order", 1))
    except (ValueError, TypeError):
        return (
            jsonify({"error": "Validation failed", "message": "The 'order' field must be an integer."}),
            400,
        )

    # Validate probability (0 - 100)
    try:
        probability = int(data.get("probability", 100))
        if probability < 0 or probability > 100:
            raise ValueError()
    except (ValueError, TypeError):
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'probability' field must be an integer between 0 and 100.",
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
                    "message": "Stage created successfully.",
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
                    "error": "Internal error",
                    "message": f"Could not create the stage: {str(exc)}",
                }
            ),
            500,
        )


@stage_bp.route("/<stage_id>", methods=["PUT"])
@tenant_required
def update_stage(stage_id):
    """Updates an existing workspace stage."""
    stage = Stage.query.filter_by(id=stage_id, tenant_id=g.tenant_id).first()
    if not stage:
        return (
            jsonify({"error": "Not found", "message": "The requested stage does not exist."}),
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
        stage.name = name

    if "order" in data:
        try:
            stage.order = int(data["order"])
        except (ValueError, TypeError):
            return (
                jsonify({"error": "Validation failed", "message": "The 'order' field must be an integer."}),
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
                jsonify({"error": "Validation failed", "message": "The 'probability' field must be between 0 and 100."}),
                400,
            )

    try:
        db.session.commit()
        return (
            jsonify({"message": "Stage updated successfully.", "stage": stage.to_dict()}),
            200,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not update the stage: {str(exc)}"}),
            500,
        )


@stage_bp.route("/<stage_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def delete_stage(stage_id):
    """Deletes a stage when it has no linked deals."""
    stage = Stage.query.filter_by(id=stage_id, tenant_id=g.tenant_id).first()
    if not stage:
        return (
            jsonify({"error": "Not found", "message": "The requested stage does not exist."}),
            404,
        )

    if stage.deals.count() > 0:
        return (
            jsonify(
                {
                    "error": "Operation not allowed",
                    "message": "A stage with associated deals cannot be deleted. Move them first.",
                }
            ),
            409,
        )

    try:
        db.session.delete(stage)
        db.session.commit()
        return jsonify({"message": "Stage deleted successfully."}), 200
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not delete the stage: {str(exc)}"}),
            500,
        )

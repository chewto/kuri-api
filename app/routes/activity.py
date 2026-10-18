from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models.contact import Contact
from app.models.activity_log import ActivityLog, ActivityType
from app.middlewares.tenant_context import tenant_required

activity_bp = Blueprint("activities", __name__)


@activity_bp.route("/<string:contact_id>/activities", methods=["GET"])
@tenant_required
def get_contact_activities(contact_id):
    """Lista la línea de tiempo de notas/interacciones del contacto."""
    contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
    if not contact:
        return (
            jsonify({"error": "No encontrado", "message": "Contacto no encontrado en su organización."}),
            404,
        )

    activities = (
        ActivityLog.query.filter_by(contact_id=contact.id, tenant_id=g.tenant_id)
        .order_by(ActivityLog.created_at.desc())
        .all()
    )

    return jsonify({"activities": [activity.to_dict() for activity in activities]}), 200


@activity_bp.route("/<string:contact_id>/activities", methods=["POST"])
@tenant_required
def create_contact_activity(contact_id):
    """Registra una nueva interacción (Llamada, Nota, Correo, Reunión) del usuario actual."""
    contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
    if not contact:
        return (
            jsonify({"error": "No encontrado", "message": "Contacto no encontrado en su organización."}),
            404,
        )

    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    activity_type_str = data.get("type", "note").strip().lower()

    if not content:
        return (
            jsonify({"error": "Validación fallida", "message": "El campo 'content' es requerido."}),
            400,
        )

    valid_types = [t.value for t in ActivityType]
    if activity_type_str not in valid_types:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": f"Tipo de actividad inválido. Debe ser uno de: {', '.join(valid_types)}",
                }
            ),
            400,
        )

    activity = ActivityLog(
        tenant_id=g.tenant_id,
        contact_id=contact.id,
        user_id=g.current_user_id,
        type=ActivityType(activity_type_str),
        content=content,
    )

    try:
        db.session.add(activity)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Actividad registrada exitosamente.",
                    "activity": activity.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Error interno", "message": f"No se pudo registrar la actividad: {str(exc)}"}),
            500,
        )

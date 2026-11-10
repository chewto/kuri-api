from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, g
from sqlalchemy import func
from app.extensions import db
from app.models.contact import Contact
from app.models.activity_log import ActivityLog, ActivityType
from app.middlewares.tenant_context import tenant_required

activity_bp = Blueprint("activities", __name__)


@activity_bp.route("/<string:contact_id>/activities", methods=["GET"])
@tenant_required
def get_contact_activities(contact_id):
    """Lists the contact's notes and interaction timeline."""
    contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
    if not contact:
        return (
            jsonify({"error": "Not found", "message": "Contact not found in your organization."}),
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
    """Logs a new interaction (call, note, email, or meeting) for the current user."""
    contact = Contact.query.filter_by(id=contact_id, tenant_id=g.tenant_id).first()
    if not contact:
        return (
            jsonify({"error": "Not found", "message": "Contact not found in your organization."}),
            404,
        )

    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    activity_type_str = data.get("type", "note").strip().lower()

    if not content:
        return (
            jsonify({"error": "Validation failed", "message": "The 'content' field is required."}),
            400,
        )

    valid_types = [t.value for t in ActivityType]
    if activity_type_str not in valid_types:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": f"Invalid activity type. Must be one of: {', '.join(valid_types)}",
                }
            ),
            400,
        )

    # The system clock may have millisecond resolution and return
    # the same instant for two consecutive activities. We guarantee that
    # each new activity has a timestamp strictly greater than the
    # contact's latest activity so the timeline is deterministic.
    created_at = datetime.now(timezone.utc)
    latest_created_at = (
        db.session.query(func.max(ActivityLog.created_at))
        .filter(
            ActivityLog.contact_id == contact.id,
            ActivityLog.tenant_id == g.tenant_id,
        )
        .scalar()
    )
    if latest_created_at is not None:
        candidate = (
            created_at.replace(tzinfo=None)
            if latest_created_at.tzinfo is None
            else created_at
        )
        if candidate <= latest_created_at:
            created_at = latest_created_at + timedelta(microseconds=1)

    activity = ActivityLog(
        tenant_id=g.tenant_id,
        contact_id=contact.id,
        user_id=g.current_user_id,
        type=ActivityType(activity_type_str),
        content=content,
        created_at=created_at,
    )

    try:
        db.session.add(activity)
        db.session.commit()
        return (
            jsonify(
                {
                    "message": "Activity logged successfully.",
                    "activity": activity.to_dict(),
                }
            ),
            201,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify({"error": "Internal error", "message": f"Could not log the activity: {str(exc)}"}),
            500,
        )

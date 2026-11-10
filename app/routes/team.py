import re
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.user import User, UserRole
from app.middlewares.tenant_context import tenant_required
from app.middlewares.rbac import roles_required

team_bp = Blueprint("team", __name__)

ASSIGNABLE_ROLES = {
    UserRole.TENANT_ADMIN,
    UserRole.USER,
    UserRole.AUDITOR,
}
ASSIGNABLE_ROLE_VALUES = {role.value for role in ASSIGNABLE_ROLES}
ASSIGNABLE_ROLES_BY_VALUE = {role.value: role for role in ASSIGNABLE_ROLES}

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _role_name(role):
    if isinstance(role, UserRole):
        return role.value
    return str(role)


def _validate_role(role_value):
    """Returns the role enum, or None when the role is not assignable."""
    if not isinstance(role_value, str):
        return None
    return ASSIGNABLE_ROLES_BY_VALUE.get(role_value.strip())


@team_bp.route("/members", methods=["GET"])
@tenant_required
def get_team_members():
    """Lists all members of the current workspace, including inactive ones."""
    members = (
        User.query.filter_by(tenant_id=g.tenant_id)
        .order_by(User.created_at.asc())
        .all()
    )

    return (
        jsonify(
            {
                "items": [member.to_dict() for member in members],
                "total": len(members),
            }
        ),
        200,
    )


@team_bp.route("/invite", methods=["POST"])
@tenant_required
@roles_required(["TenantAdmin"])
def invite_team_member():
    """Registers a new user in the workspace with an assignable initial role."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The request body must be a JSON object.",
                }
            ),
            400,
        )

    email = str(data.get("email", "")).strip().lower()
    if not email or not EMAIL_REGEX.fullmatch(email):
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'email' field is required and must be a valid email address.",
                }
            ),
            400,
        )

    raw_password = data.get("password")
    password = raw_password.strip() if isinstance(raw_password, str) else ""
    if len(password) < 6:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'password' field is required and must be at least 6 characters long.",
                }
            ),
            400,
        )

    role = _validate_role(data.get("role", UserRole.USER.value))
    if role is None:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": (
                        "Invalid role. Allowed options: "
                        f"{', '.join(sorted(ASSIGNABLE_ROLE_VALUES))}."
                    ),
                }
            ),
            400,
        )

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "A user with this email address already exists.",
                }
            ),
            409,
        )

    new_user = User(
        tenant_id=g.tenant_id,
        email=email,
        role=role,
        is_active=True,
    )
    new_user.set_password(password)
    db.session.add(new_user)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "A user with this email address already exists.",
                }
            ),
            409,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not register the team member: {str(exc)}",
                }
            ),
            500,
        )

    return (
        jsonify(
            {
                "message": "Team member registered successfully.",
                "user": new_user.to_dict(),
            }
        ),
        201,
    )


@team_bp.route("/members/<string:member_id>/role", methods=["PUT"])
@tenant_required
@roles_required(["TenantAdmin"])
def update_team_member_role(member_id):
    """Updates a member's role in the current workspace."""
    member = User.query.filter_by(id=member_id, tenant_id=g.tenant_id).first()
    if not member:
        return (
            jsonify(
                {
                    "error": "Not found",
                    "message": "Team member not found in your organization.",
                }
            ),
            404,
        )

    if member.id == g.current_user_id:
        return (
            jsonify(
                {
                    "error": "Operation not allowed",
                    "message": "You cannot change your own role.",
                }
            ),
            400,
        )

    if _role_name(member.role) == UserRole.SUPER_ADMIN.value:
        return (
            jsonify(
                {
                    "error": "Access denied",
                    "message": "SuperAdmins cannot be modified from this module.",
                }
            ),
            403,
        )

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The request body must be a JSON object.",
                }
            ),
            400,
        )

    role = _validate_role(data.get("role"))
    if role is None:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": (
                        "The 'role' field is required. Allowed options: "
                        f"{', '.join(sorted(ASSIGNABLE_ROLE_VALUES))}."
                    ),
                }
            ),
            400,
        )

    member.role = role

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not update the member role: {str(exc)}",
                }
            ),
            500,
        )

    return (
        jsonify(
            {
                "message": "Member role updated successfully.",
                "user": member.to_dict(),
            }
        ),
        200,
    )


@team_bp.route("/members/<string:member_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def deactivate_team_member(member_id):
    """Soft-deactivates a member of the current workspace."""
    member = User.query.filter_by(id=member_id, tenant_id=g.tenant_id).first()
    if not member:
        return (
            jsonify(
                {
                    "error": "Not found",
                    "message": "Team member not found in your organization.",
                }
            ),
            404,
        )

    if member.id == g.current_user_id:
        return (
            jsonify(
                {
                    "error": "Operation not allowed",
                    "message": "You cannot deactivate your own account.",
                }
            ),
            400,
        )

    if _role_name(member.role) == UserRole.SUPER_ADMIN.value:
        return (
            jsonify(
                {
                    "error": "Access denied",
                    "message": "SuperAdmins cannot be deactivated from this module.",
                }
            ),
            403,
        )

    if member.is_active and _role_name(member.role) == UserRole.TENANT_ADMIN.value:
        active_admins = User.query.filter_by(
            tenant_id=g.tenant_id,
            role=UserRole.TENANT_ADMIN,
            is_active=True,
        ).count()
        if active_admins <= 1:
            return (
                jsonify(
                    {
                        "error": "Operation not allowed",
                        "message": "The last active TenantAdmin cannot be deactivated.",
                    }
                ),
                409,
            )

    already_inactive = not member.is_active
    member.is_active = False

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal error",
                    "message": f"Could not deactivate the team member: {str(exc)}",
                }
            ),
            500,
        )

    message = (
        "The team member was already inactive."
        if already_inactive
        else "Team member deactivated successfully."
    )
    return jsonify({"message": message, "user": member.to_dict()}), 200

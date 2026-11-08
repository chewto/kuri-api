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
    """Devuelve el enum de rol o None si no es asignable."""
    if not isinstance(role_value, str):
        return None
    return ASSIGNABLE_ROLES_BY_VALUE.get(role_value.strip())


@team_bp.route("/members", methods=["GET"])
@tenant_required
def get_team_members():
    """Lista todos los miembros del tenant actual, incluidos los inactivos."""
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
    """Registra un nuevo usuario dentro del tenant con un rol inicial asignable."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El cuerpo de la petición debe ser un objeto JSON.",
                }
            ),
            400,
        )

    email = str(data.get("email", "")).strip().lower()
    if not email or not EMAIL_REGEX.fullmatch(email):
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El campo 'email' es requerido y debe tener un formato válido.",
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
                    "error": "Validación fallida",
                    "message": "El campo 'password' es requerido y debe tener al menos 6 caracteres.",
                }
            ),
            400,
        )

    role = _validate_role(data.get("role", UserRole.USER.value))
    if role is None:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": (
                        "Rol inválido. Opciones permitidas: "
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
                    "error": "Conflicto",
                    "message": "Ya existe un usuario registrado con este correo electrónico.",
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
                    "error": "Conflicto",
                    "message": "Ya existe un usuario registrado con este correo electrónico.",
                }
            ),
            409,
        )
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Error interno",
                    "message": f"No se pudo registrar el miembro del equipo: {str(exc)}",
                }
            ),
            500,
        )

    return (
        jsonify(
            {
                "message": "Miembro del equipo registrado exitosamente.",
                "user": new_user.to_dict(),
            }
        ),
        201,
    )


@team_bp.route("/members/<string:member_id>/role", methods=["PUT"])
@tenant_required
@roles_required(["TenantAdmin"])
def update_team_member_role(member_id):
    """Actualiza el rol de un miembro del tenant actual."""
    member = User.query.filter_by(id=member_id, tenant_id=g.tenant_id).first()
    if not member:
        return (
            jsonify(
                {
                    "error": "No encontrado",
                    "message": "Miembro del equipo no encontrado en su organización.",
                }
            ),
            404,
        )

    if member.id == g.current_user_id:
        return (
            jsonify(
                {
                    "error": "Operación no permitida",
                    "message": "No puede cambiar su propio rol.",
                }
            ),
            400,
        )

    if _role_name(member.role) == UserRole.SUPER_ADMIN.value:
        return (
            jsonify(
                {
                    "error": "Acceso denegado",
                    "message": "No está permitido modificar a un SuperAdmin desde este módulo.",
                }
            ),
            403,
        )

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El cuerpo de la petición debe ser un objeto JSON.",
                }
            ),
            400,
        )

    role = _validate_role(data.get("role"))
    if role is None:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": (
                        "El campo 'role' es requerido. Opciones permitidas: "
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
                    "error": "Error interno",
                    "message": f"No se pudo actualizar el rol del miembro: {str(exc)}",
                }
            ),
            500,
        )

    return (
        jsonify(
            {
                "message": "Rol del miembro actualizado exitosamente.",
                "user": member.to_dict(),
            }
        ),
        200,
    )


@team_bp.route("/members/<string:member_id>", methods=["DELETE"])
@tenant_required
@roles_required(["TenantAdmin"])
def deactivate_team_member(member_id):
    """Desactiva lógicamente a un miembro del tenant actual."""
    member = User.query.filter_by(id=member_id, tenant_id=g.tenant_id).first()
    if not member:
        return (
            jsonify(
                {
                    "error": "No encontrado",
                    "message": "Miembro del equipo no encontrado en su organización.",
                }
            ),
            404,
        )

    if member.id == g.current_user_id:
        return (
            jsonify(
                {
                    "error": "Operación no permitida",
                    "message": "No puede desactivar su propia cuenta.",
                }
            ),
            400,
        )

    if _role_name(member.role) == UserRole.SUPER_ADMIN.value:
        return (
            jsonify(
                {
                    "error": "Acceso denegado",
                    "message": "No está permitido desactivar a un SuperAdmin desde este módulo.",
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
                        "error": "Operación no permitida",
                        "message": "No es posible desactivar al último TenantAdmin activo.",
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
                    "error": "Error interno",
                    "message": f"No se pudo desactivar al miembro del equipo: {str(exc)}",
                }
            ),
            500,
        )

    message = (
        "El miembro del equipo ya se encontraba inactivo."
        if already_inactive
        else "Miembro del equipo desactivado exitosamente."
    )
    return jsonify({"message": message, "user": member.to_dict()}), 200

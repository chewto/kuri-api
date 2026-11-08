from functools import wraps
from flask import g, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from app.models.tenant import Tenant
from app.models.user import User, UserRole


def tenant_required(fn):
    """Decorador para rutas protegidas que extrae y valida el contexto del Tenant desde el token JWT.

    1. Valida el JWT en la cabecera Authorization: Bearer <token>.
    2. Extrae tenant_id y role desde los claims personalizados del JWT.
    3. Asigna g.tenant_id, g.current_user_id y g.user_role en el contexto de la petición.
    4. Verifica que el Tenant asociado exista y se encuentre activo.
    5. Verifica que el usuario exista en ese Tenant y siga activo, exponiendo
       g.current_user y g.current_role para el control de acceso por roles.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Valida presencia y vigencia del JWT
        verify_jwt_in_request()

        claims = get_jwt()
        user_id = get_jwt_identity()
        tenant_id = claims.get("tenant_id")
        role = claims.get("role")

        if not tenant_id:
            return (
                jsonify(
                    {
                        "error": "Aislamiento de Tenant inválido",
                        "message": "El token provisto no incluye un identificador de Tenant válido.",
                    }
                ),
                403,
            )

        # Validar en base de datos si el tenant está activo
        tenant = Tenant.query.filter_by(id=tenant_id).first()
        if not tenant:
            return (
                jsonify(
                    {
                        "error": "Tenant no encontrado",
                        "message": "La organización solicitada no existe.",
                    }
                ),
                404,
            )

        if not tenant.is_active:
            return (
                jsonify(
                    {
                        "error": "Tenant suspendido",
                        "message": "La organización asociada se encuentra inactiva.",
                    }
                ),
                403,
            )

        # Validar que el usuario autenticado pertenezca al tenant y siga activo.
        # Esto permite revocar el acceso de inmediato al desactivar a un miembro
        # sin esperar a que expire su token JWT.
        user = User.query.filter_by(id=user_id, tenant_id=tenant_id).first()
        if not user:
            return (
                jsonify(
                    {
                        "error": "Usuario no válido",
                        "message": "El usuario del token no existe en el Tenant actual.",
                    }
                ),
                401,
            )

        if not user.is_active:
            return (
                jsonify(
                    {
                        "error": "Cuenta inactiva",
                        "message": "La cuenta de usuario se encuentra deshabilitada.",
                    }
                ),
                403,
            )

        # Inyectar al contexto global de la solicitud Flask
        g.tenant_id = tenant_id
        g.tenant = tenant
        g.current_user_id = user_id
        g.current_user = user
        g.user_role = role
        g.current_role = (
            user.role.value if isinstance(user.role, UserRole) else str(user.role)
        )

        return fn(*args, **kwargs)

    return wrapper

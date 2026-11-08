from functools import wraps
from flask import g, jsonify
from flask_jwt_extended import get_jwt, verify_jwt_in_request
from app.models.user import UserRole


def _normalize_role(role):
    """Convierte un rol de enum o string a su representación canónica."""
    if isinstance(role, UserRole):
        return role.value
    if role is None:
        return None
    return str(role)


def _forbidden(message):
    return jsonify({"error": "Acceso denegado", "message": message}), 403


def roles_required(*roles):
    """Restringe el acceso a los roles indicados.

    Acepta tanto una lista como roles posicionales:
        @roles_required(['TenantAdmin'])
        @roles_required('TenantAdmin', 'Auditor')

    Debe aplicarse debajo de ``@tenant_required`` para que el contexto del
    tenant y el usuario autenticado ya estén disponibles en ``g``. El claim
    ``role`` del JWT debe estar permitido y, si el usuario fue cargado desde
    la base de datos, su rol vigente también, evitando privilegios residuales
    después de una degradación de rol.
    """
    if len(roles) == 1 and isinstance(roles[0], (list, tuple, set, frozenset)):
        roles = tuple(roles[0])

    allowed_roles = {_normalize_role(role) for role in roles}
    allowed_roles.discard(None)

    if not allowed_roles:
        raise ValueError("roles_required debe recibir al menos un rol válido.")

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if getattr(g, "user_role", None) is None:
                # Uso defensivo del decorador sin tenant_required.
                verify_jwt_in_request()
                g.user_role = get_jwt().get("role")

            token_role = _normalize_role(g.user_role)
            if token_role not in allowed_roles:
                return _forbidden(
                    "Su rol no tiene permisos para realizar esta operación. "
                    f"Roles permitidos: {', '.join(sorted(allowed_roles))}."
                )

            current_user = getattr(g, "current_user", None)
            if current_user is not None:
                current_role = _normalize_role(current_user.role)
                if current_role not in allowed_roles:
                    return _forbidden(
                        "Su rol vigente no tiene permisos para realizar esta operación. "
                        "Inicie sesión nuevamente si su rol fue actualizado."
                    )

            return fn(*args, **kwargs)

        return wrapper

    return decorator

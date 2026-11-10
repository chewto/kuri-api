from functools import wraps
from flask import g, jsonify
from flask_jwt_extended import get_jwt, verify_jwt_in_request
from app.models.user import UserRole


def _normalize_role(role):
    """Converts an enum or string role to its canonical representation."""
    if isinstance(role, UserRole):
        return role.value
    if role is None:
        return None
    return str(role)


def _forbidden(message):
    return jsonify({"error": "Access denied", "message": message}), 403


def roles_required(*roles):
    """Restricts access to the specified roles.

    Accepts either a list or positional roles:
        @roles_required(['TenantAdmin'])
        @roles_required('TenantAdmin', 'Auditor')

    Must be applied below ``@tenant_required`` so the tenant context and the
    authenticated user are already available in ``g``. The JWT ``role`` claim
    must be allowed and, if the user was loaded from the database, their
    current role must be allowed too, preventing residual privileges after a
    role downgrade.
    """
    if len(roles) == 1 and isinstance(roles[0], (list, tuple, set, frozenset)):
        roles = tuple(roles[0])

    allowed_roles = {_normalize_role(role) for role in roles}
    allowed_roles.discard(None)

    if not allowed_roles:
        raise ValueError("roles_required must receive at least one valid role.")

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if getattr(g, "user_role", None) is None:
                # Defensive use of the decorator without tenant_required.
                verify_jwt_in_request()
                g.user_role = get_jwt().get("role")

            token_role = _normalize_role(g.user_role)
            if token_role not in allowed_roles:
                return _forbidden(
                    "Your role is not allowed to perform this operation. "
                    f"Allowed roles: {', '.join(sorted(allowed_roles))}."
                )

            current_user = getattr(g, "current_user", None)
            if current_user is not None:
                current_role = _normalize_role(current_user.role)
                if current_role not in allowed_roles:
                    return _forbidden(
                        "Your current role is not allowed to perform this operation. "
                        "Sign in again if your role was updated."
                    )

            return fn(*args, **kwargs)

        return wrapper

    return decorator

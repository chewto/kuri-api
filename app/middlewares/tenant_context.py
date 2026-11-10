from functools import wraps
from flask import g, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from app.models.tenant import Tenant
from app.models.user import User, UserRole


def tenant_required(fn):
    """Decorator for protected routes that extracts and validates the workspace context from the JWT.

    1. Validates the JWT in the Authorization: Bearer <token> header.
    2. Extracts tenant_id and role from the JWT custom claims.
    3. Sets g.tenant_id, g.current_user_id, and g.user_role on the request context.
    4. Verifies that the associated workspace exists and is active.
    5. Verifies that the user exists in that workspace and is still active,
       exposing g.current_user and g.current_role for role-based access control.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Validate JWT presence and validity
        verify_jwt_in_request()

        claims = get_jwt()
        user_id = get_jwt_identity()
        tenant_id = claims.get("tenant_id")
        role = claims.get("role")

        if not tenant_id:
            return (
                jsonify(
                    {
                        "error": "Invalid workspace isolation",
                        "message": "The provided token does not include a valid workspace identifier.",
                    }
                ),
                403,
            )

        # Check in the database whether the workspace is active
        tenant = Tenant.query.filter_by(id=tenant_id).first()
        if not tenant:
            return (
                jsonify(
                    {
                        "error": "Workspace not found",
                        "message": "The requested organization does not exist.",
                    }
                ),
                404,
            )

        if not tenant.is_active:
            return (
                jsonify(
                    {
                        "error": "Workspace suspended",
                        "message": "The associated organization is inactive.",
                    }
                ),
                403,
            )

        # Verify that the authenticated user belongs to the workspace and is active.
        # This allows access to be revoked immediately when a member is deactivated
        # without waiting for the JWT to expire.
        user = User.query.filter_by(id=user_id, tenant_id=tenant_id).first()
        if not user:
            return (
                jsonify(
                    {
                        "error": "Invalid user",
                        "message": "The user in the token does not exist in the current workspace.",
                    }
                ),
                401,
            )

        if not user.is_active:
            return (
                jsonify(
                    {
                        "error": "Inactive account",
                        "message": "This user account is disabled.",
                    }
                ),
                403,
            )

        # Inject into Flask's global request context
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

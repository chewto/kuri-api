from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import create_access_token, create_refresh_token
from app.extensions import db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.middlewares.tenant_context import tenant_required

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register-tenant", methods=["POST"])
def register_tenant():
    """Registers a new workspace together with its initial administrator user (TenantAdmin)."""
    data = request.get_json(silent=True) or {}

    tenant_name = data.get("tenant_name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    plan = data.get("plan", "free").strip()

    # Basic validation
    if not tenant_name:
        return jsonify({"error": "Validation failed", "message": "The 'tenant_name' field is required."}), 400

    if not email:
        return jsonify({"error": "Validation failed", "message": "The 'email' field is required."}), 400

    if not password or len(password) < 6:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "The 'password' field is required and must be at least 6 characters long.",
                }
            ),
            400,
        )

    # Check whether the user already exists
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

    try:
        # Atomic transaction: create the workspace and the TenantAdmin user
        new_tenant = Tenant(name=tenant_name, plan=plan)
        db.session.add(new_tenant)
        db.session.flush()  # Read the ID assigned to new_tenant

        admin_user = User(
            tenant_id=new_tenant.id,
            email=email,
            role=UserRole.TENANT_ADMIN,
        )
        admin_user.set_password(password)
        db.session.add(admin_user)
        db.session.commit()

        # Add custom JWT claims
        role_str = admin_user.role.value if isinstance(admin_user.role, UserRole) else str(admin_user.role)
        additional_claims = {
            "tenant_id": new_tenant.id,
            "role": role_str,
        }

        access_token = create_access_token(
            identity=admin_user.id,
            additional_claims=additional_claims,
        )
        refresh_token = create_refresh_token(
            identity=admin_user.id,
            additional_claims=additional_claims,
        )

        return (
            jsonify(
                {
                    "message": "Organization and administrator user created successfully.",
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "tenant": new_tenant.to_dict(),
                    "user": admin_user.to_dict(),
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
                    "message": f"Could not complete registration: {str(exc)}",
                }
            ),
            500,
        )


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticates a user's credentials and issues JWT tokens associated with their workspace."""
    data = request.get_json(silent=True) or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "message": "You must provide 'email' and 'password'.",
                }
            ),
            400,
        )

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return (
            jsonify(
                {
                    "error": "Invalid credentials",
                    "message": "Incorrect email or password.",
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

    tenant = Tenant.query.filter_by(id=user.tenant_id).first()
    if not tenant or not tenant.is_active:
        return (
            jsonify(
                {
                    "error": "Inactive organization",
                    "message": "The organization associated with this account is inactive.",
                }
            ),
            403,
        )

    role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    additional_claims = {
        "tenant_id": user.tenant_id,
        "role": role_str,
    }

    access_token = create_access_token(
        identity=user.id,
        additional_claims=additional_claims,
    )
    refresh_token = create_refresh_token(
        identity=user.id,
        additional_claims=additional_claims,
    )

    return (
        jsonify(
            {
                "message": "Signed in successfully.",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user": user.to_dict(),
            }
        ),
        200,
    )


@auth_bp.route("/me", methods=["GET"])
@tenant_required
def me():
    """JWT-protected route validated against the current workspace. Returns the authenticated user's full profile."""
    user = User.query.filter_by(id=g.current_user_id, tenant_id=g.tenant_id).first()

    if not user:
        return (
            jsonify(
                {
                    "error": "User not found",
                    "message": "The user record was not found in the current workspace.",
                }
            ),
            404,
        )

    return (
        jsonify(
            {
                "user": user.to_dict(),
                "tenant": g.tenant.to_dict(),
            }
        ),
        200,
    )

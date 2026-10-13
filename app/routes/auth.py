from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import create_access_token, create_refresh_token
from app.extensions import db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.middlewares.tenant_context import tenant_required

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register-tenant", methods=["POST"])
def register_tenant():
    """Registra una nueva organización (Tenant) junto con su usuario administrador inicial (TenantAdmin)."""
    data = request.get_json(silent=True) or {}

    tenant_name = data.get("tenant_name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    plan = data.get("plan", "free").strip()

    # Validaciones básicas
    if not tenant_name:
        return jsonify({"error": "Validación fallida", "message": "El campo 'tenant_name' es requerido."}), 400

    if not email:
        return jsonify({"error": "Validación fallida", "message": "El campo 'email' es requerido."}), 400

    if not password or len(password) < 6:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "El campo 'password' es requerido y debe tener al menos 6 caracteres.",
                }
            ),
            400,
        )

    # Verificar si el usuario ya existe
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

    try:
        # Transacción atómica: Crear Tenant + User TenantAdmin
        new_tenant = Tenant(name=tenant_name, plan=plan)
        db.session.add(new_tenant)
        db.session.flush()  # Obtener el ID asignado a new_tenant

        admin_user = User(
            tenant_id=new_tenant.id,
            email=email,
            role=UserRole.TENANT_ADMIN,
        )
        admin_user.set_password(password)
        db.session.add(admin_user)
        db.session.commit()

        # Generar claims adicionales para el JWT
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
                    "message": "Organización y usuario administrador creados exitosamente.",
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
                    "error": "Error interno",
                    "message": f"No se pudo completar el registro: {str(exc)}",
                }
            ),
            500,
        )


@auth_bp.route("/login", methods=["POST"])
def login():
    """Autentica las credenciales de un usuario y emite tokens JWT asociados a su Tenant."""
    data = request.get_json(silent=True) or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return (
            jsonify(
                {
                    "error": "Validación fallida",
                    "message": "Debe proporcionar 'email' y 'password'.",
                }
            ),
            400,
        )

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return (
            jsonify(
                {
                    "error": "Credenciales inválidas",
                    "message": "Correo electrónico o contraseña incorrectos.",
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

    tenant = Tenant.query.filter_by(id=user.tenant_id).first()
    if not tenant or not tenant.is_active:
        return (
            jsonify(
                {
                    "error": "Organización inactiva",
                    "message": "La organización asociada a esta cuenta se encuentra inactiva.",
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
                "message": "Inicio de sesión exitoso.",
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
    """Ruta protegida por JWT y validada para el Tenant actual. Retorna el perfil completo del usuario autenticado."""
    user = User.query.filter_by(id=g.current_user_id, tenant_id=g.tenant_id).first()

    if not user:
        return (
            jsonify(
                {
                    "error": "Usuario no encontrado",
                    "message": "No se encontró el registro del usuario en el Tenant actual.",
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

import enum
import uuid
from datetime import datetime, timezone
from app.extensions import db
from app.utils.security import hash_password, verify_password


class UserRole(str, enum.Enum):
    """Roles available in the system."""

    SUPER_ADMIN = "SuperAdmin"
    TENANT_ADMIN = "TenantAdmin"
    USER = "User"
    AUDITOR = "Auditor"


class User(db.Model):
    """User belonging to a specific workspace."""

    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.Enum(
            UserRole,
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=False,
        ),
        nullable=False,
        default=UserRole.USER,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Inverse relationship to the workspace
    tenant = db.relationship("Tenant", back_populates="users")

    def set_password(self, password: str) -> None:
        """Hashes and stores the password securely."""
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        """Checks the plain-text password against the stored hash."""
        return verify_password(password, self.password_hash)

    def __repr__(self):
        return f"<User {self.email} ({self.role.value if isinstance(self.role, UserRole) else self.role})>"

    def to_dict(self):
        role_value = self.role.value if isinstance(self.role, UserRole) else str(self.role)
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "role": role_value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

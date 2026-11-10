import uuid
from datetime import datetime, timezone
from app.extensions import db


class Tenant(db.Model):
    """An organization or tenant in the multi-tenant architecture."""

    __tablename__ = "tenants"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False)
    plan = db.Column(db.String(50), nullable=False, default="free")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # One-to-many relationship with workspace users
    users = db.relationship("User", back_populates="tenant", cascade="all, delete-orphan", lazy="dynamic")

    def __repr__(self):
        return f"<Tenant {self.name} ({self.id})>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "plan": self.plan,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

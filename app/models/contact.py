import uuid
from datetime import datetime, timezone
from app.extensions import db


class Contact(db.Model):
    """Modelo de Contacto corporativo perteneciente a un Tenant específico."""

    __tablename__ = "contacts"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = db.Column(
        db.String(36),
        db.ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=True)
    email = db.Column(db.String(120), nullable=True, index=True)
    phone = db.Column(db.String(30), nullable=True)
    position = db.Column(db.String(80), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relaciones
    tenant = db.relationship("Tenant")
    company = db.relationship("Company", back_populates="contacts")
    activities = db.relationship(
        "ActivityLog",
        back_populates="contact",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<Contact {self.first_name} {self.last_name or ''} ({self.id})>"

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "company_name": self.company.name if self.company else None,
            "company": self.company.to_dict() if self.company else None,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "position": self.position,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

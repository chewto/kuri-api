import uuid
from datetime import datetime, timezone
from app.extensions import db


class Company(db.Model):
    """Customer company belonging to a specific workspace."""

    __tablename__ = "companies"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False, index=True)
    tax_id = db.Column(db.String(50), nullable=True)
    industry = db.Column(db.String(80), nullable=True)
    website = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = db.relationship("Tenant")
    contacts = db.relationship(
        "Contact",
        back_populates="company",
        cascade="save-update, merge",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<Company {self.name} ({self.id})>"

    def to_dict(self, include_contacts: bool = False):
        data = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "tax_id": self.tax_id,
            "industry": self.industry,
            "website": self.website,
            "phone": self.phone,
            "address": self.address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_contacts:
            data["contacts"] = [c.to_dict() for c in self.contacts.all()]
        return data

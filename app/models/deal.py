import uuid
from datetime import datetime, timezone
from app.extensions import db


class Deal(db.Model):
    """Modelo de Oportunidad de Negocio (Deal) perteneciente a un Tenant."""

    __tablename__ = "deals"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = db.Column(
        db.String(36),
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id = db.Column(
        db.String(36),
        db.ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage_id = db.Column(
        db.String(36),
        db.ForeignKey("stages.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(120), nullable=False)
    value = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    expected_close_date = db.Column(db.Date, nullable=True)
    status = db.Column(
        db.Enum("open", "won", "lost", name="deal_status_enum"),
        nullable=False,
        default="open",
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relaciones
    tenant = db.relationship("Tenant")
    # PostgreSQL aplica ON DELETE CASCADE sobre companies -> deals. Con
    # passive_deletes se evita que el ORM intente poner company_id=NULL en una
    # columna NOT NULL antes de que actúe la FK.
    company = db.relationship(
        "Company",
        backref=db.backref("deals", lazy="dynamic", passive_deletes=True),
    )
    contact = db.relationship("Contact", backref=db.backref("deals", lazy="dynamic"))
    stage = db.relationship("Stage", back_populates="deals")

    def __repr__(self):
        return f"<Deal {self.title} ({self.status}) - {self.value}>"

    def to_dict(self):
        contact_display = None
        if self.contact:
            contact_display = f"{self.contact.first_name} {self.contact.last_name or ''}".strip()

        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "company_name": self.company.name if self.company else None,
            "contact_id": self.contact_id,
            "contact_name": contact_display,
            "stage_id": self.stage_id,
            "stage_name": self.stage.name if self.stage else None,
            "stage_order": self.stage.order if self.stage else None,
            "stage_probability": self.stage.probability if self.stage else None,
            "title": self.title,
            "value": float(self.value) if self.value is not None else 0.0,
            "expected_close_date": self.expected_close_date.isoformat() if self.expected_close_date else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

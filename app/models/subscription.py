import uuid
from datetime import datetime, timezone
from app.extensions import db


class Subscription(db.Model):
    """Recurring software or service subscription (SaaS/OPEX)."""

    __tablename__ = "subscriptions"

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
    category_id = db.Column(
        db.String(36),
        db.ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    cost = db.Column(db.Numeric(10, 2), nullable=False)
    billing_cycle = db.Column(
        db.Enum("monthly", "yearly", "quarterly", name="billing_cycle_enum"),
        nullable=False,
        default="monthly",
    )
    next_billing_date = db.Column(db.Date, nullable=False)
    status = db.Column(
        db.Enum("active", "paused", "cancelled", name="subscription_status_enum"),
        nullable=False,
        default="active",
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = db.relationship("Tenant")
    company = db.relationship("Company", backref=db.backref("subscriptions", lazy="dynamic"))
    category = db.relationship("Category", backref=db.backref("subscriptions", lazy="dynamic"))

    def __repr__(self):
        return f"<Subscription {self.name} ({self.cost} {self.billing_cycle})>"

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "company_name": self.company.name if self.company else None,
            "category_id": self.category_id,
            "category_name": self.category.name if self.category else None,
            "category_color": self.category.color if self.category else None,
            "name": self.name,
            "cost": float(self.cost) if self.cost is not None else 0.0,
            "billing_cycle": self.billing_cycle,
            "next_billing_date": self.next_billing_date.isoformat() if self.next_billing_date else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

import uuid
from datetime import datetime, timezone
from app.extensions import db


class Transaction(db.Model):
    """Financial transaction (cash inflow and outflow movements)."""

    __tablename__ = "transactions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id = db.Column(
        db.String(36),
        db.ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    company_id = db.Column(
        db.String(36),
        db.ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    type = db.Column(
        db.Enum("income", "expense", name="transaction_type_enum"),
        nullable=False,
    )
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = db.relationship("Tenant")
    category = db.relationship("Category", backref=db.backref("transactions", lazy="dynamic"))
    company = db.relationship("Company", backref=db.backref("transactions", lazy="dynamic"))

    def __repr__(self):
        return f"<Transaction {self.type} {self.amount}: {self.description}>"

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "category_id": self.category_id,
            "category_name": self.category.name if self.category else None,
            "category_color": self.category.color if self.category else None,
            "company_id": self.company_id,
            "company_name": self.company.name if self.company else None,
            "type": self.type,
            "amount": float(self.amount) if self.amount is not None else 0.0,
            "description": self.description,
            "date": self.date.isoformat() if self.date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

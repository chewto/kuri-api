import uuid
from datetime import datetime, timezone
from app.extensions import db

DEFAULT_STAGES = [
    {"name": "Prospecting", "order": 1, "probability": 10},
    {"name": "Qualified", "order": 2, "probability": 25},
    {"name": "Proposal Sent", "order": 3, "probability": 50},
    {"name": "Negotiation", "order": 4, "probability": 75},
    {"name": "Closed Won", "order": 5, "probability": 100},
    {"name": "Closed Lost", "order": 6, "probability": 0},
]


class Stage(db.Model):
    """Sales pipeline stage belonging to a workspace."""

    __tablename__ = "stages"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(80), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=1)
    probability = db.Column(db.Integer, nullable=False, default=100)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = db.relationship("Tenant")
    deals = db.relationship(
        "Deal",
        back_populates="stage",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<Stage {self.name} (order={self.order}, prob={self.probability}%)>"

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "order": self.order,
            "probability": self.probability,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

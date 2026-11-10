import enum
import uuid
from datetime import datetime, timezone
from app.extensions import db


class ActivityType(str, enum.Enum):
    """Types of customer interactions and notes."""

    NOTE = "note"
    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"


class ActivityLog(db.Model):
    """Activity and interaction log entries associated with a contact."""

    __tablename__ = "activity_logs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id = db.Column(
        db.String(36),
        db.ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    type = db.Column(
        db.Enum(
            ActivityType,
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=False,
        ),
        nullable=False,
        default=ActivityType.NOTE,
    )
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = db.relationship("Tenant")
    contact = db.relationship("Contact", back_populates="activities")
    user = db.relationship("User")

    def __repr__(self):
        return f"<ActivityLog {self.type} ({self.id}) on Contact {self.contact_id}>"

    def to_dict(self):
        type_val = self.type.value if isinstance(self.type, ActivityType) else str(self.type)
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "contact_id": self.contact_id,
            "user_id": self.user_id,
            "user_email": self.user.email if self.user else None,
            "type": type_val,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

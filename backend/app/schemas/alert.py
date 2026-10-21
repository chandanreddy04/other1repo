from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.alert import AlertStatus, AlertType


class AlertBase(BaseModel):
    alert_type: AlertType
    message: str | None = None


class AlertCreate(AlertBase):
    session_id: UUID | None = None
    # Exactly one recipient: an app-account contact (sent_to_user_id) or a
    # phone-only contact (sent_to_phone_id). Phone-only alerts let SMS-only
    # circle members' delivery failures be tracked + retried like app contacts.
    sent_to_user_id: UUID | None = None
    sent_to_phone_id: UUID | None = None


class AlertUpdate(BaseModel):
    alert_type: AlertType | None = None
    message: str | None = None
    status: AlertStatus | None = None
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    failed_at: datetime | None = None

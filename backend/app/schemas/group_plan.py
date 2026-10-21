import uuid
from datetime import datetime

from pydantic import BaseModel


class GroupPlanMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str | None = None
    role: str
    joined_at: datetime


class GroupPlanResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    owner_name: str | None = None
    invite_code: str
    max_members: int
    member_count: int
    members: list[GroupPlanMemberResponse]
    created_at: datetime

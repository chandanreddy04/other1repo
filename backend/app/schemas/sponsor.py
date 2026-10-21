from pydantic import BaseModel, Field


class CreateSponsorshipRequest(BaseModel):
    target_phone: str = Field(..., description="Phone number of the person being asked to gift")

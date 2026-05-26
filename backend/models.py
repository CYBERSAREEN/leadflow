from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str


class LeadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., min_length=5, max_length=20)
    source: str = Field(default="manual", max_length=50)

    @validator("phone")
    def clean_phone(cls, v):
        # Strip common formatting
        cleaned = v.replace("+", "").replace(" ", "").replace("-", "").strip()
        if not cleaned.isdigit():
            raise ValueError("Phone must contain only digits")
        return cleaned

    @validator("source")
    def validate_source(cls, v):
        allowed = {"manual", "whatsapp", "facebook", "instagram", "referral", "website", "other"}
        if v.lower() not in allowed:
            return "manual"
        return v.lower()


class LeadUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=5000)
    follow_up_date: Optional[str] = None
    ai_score: Optional[int] = Field(None, ge=0, le=100)
    ai_summary: Optional[str] = Field(None, max_length=2000)

    @validator("status")
    def validate_status(cls, v):
        if v is None:
            return v
        allowed = {"new", "contacted", "interested", "converted", "lost"}
        if v.lower() not in allowed:
            raise ValueError(f"Status must be one of: {', '.join(allowed)}")
        return v.lower()


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)


class InboundMessageRequest(BaseModel):
    phone: str
    body: str
    wa_message_id: Optional[str] = None
    timestamp: Optional[int] = None
    notify_name: Optional[str] = None


class SuggestReplyRequest(BaseModel):
    lead_id: int = Field(..., gt=0)


class LeadResponse(BaseModel):
    id: int
    name: str
    phone: str
    source: str
    status: str
    ai_score: int
    ai_summary: str
    notes: str
    created_at: Optional[str]
    last_contacted: Optional[str]
    follow_up_date: Optional[str]
    user_id: Optional[int] = None

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class LeadCreate(BaseModel):
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=5)
    source: str = Field(default="manual")


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    follow_up_date: Optional[str] = None
    ai_score: Optional[int] = None
    ai_summary: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)


class InboundMessageRequest(BaseModel):
    phone: str
    body: str
    wa_message_id: Optional[str] = None
    timestamp: Optional[int] = None
    notify_name: Optional[str] = None


class SuggestReplyRequest(BaseModel):
    lead_id: int


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

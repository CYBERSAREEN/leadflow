import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from backend import database
from backend.models import LeadCreate, LeadUpdate, SendMessageRequest
from backend.services import groq_service, whatsapp_bridge

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/leads")
async def get_leads(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
):
    try:
        if search:
            leads = database.search_leads(search)
            if status:
                leads = [l for l in leads if l["status"] == status]
            return {"leads": leads, "total": len(leads)}
        leads = database.get_all_leads(status=status, limit=limit, offset=offset)
        return {"leads": leads, "total": len(leads)}
    except Exception as e:
        logger.error(f"GET /leads error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: int):
    try:
        lead = database.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return lead
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /leads/{lead_id} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leads", status_code=201)
async def create_lead(body: LeadCreate):
    try:
        existing = database.get_lead_by_phone(body.phone)
        if existing:
            raise HTTPException(status_code=409, detail="Lead with this phone number already exists")
        lead = database.create_lead(name=body.name, phone=body.phone, source=body.source)
        if not lead:
            raise HTTPException(status_code=500, detail="Failed to create lead")
        return lead
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /leads error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/leads/{lead_id}")
async def update_lead(lead_id: int, body: LeadUpdate):
    try:
        lead = database.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        if not update_data:
            return lead
        updated = database.update_lead(lead_id, **update_data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update lead")
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PUT /leads/{lead_id} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/leads/{lead_id}")
async def delete_lead(lead_id: int):
    try:
        lead = database.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        success = database.delete_lead(lead_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete lead")
        return {"message": "Lead deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DELETE /leads/{lead_id} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leads/{lead_id}/score")
async def score_lead(lead_id: int):
    try:
        lead = database.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        messages = database.get_messages_for_lead(lead_id)
        message_bodies = [m["body"] for m in messages]

        result = groq_service.score_lead(lead["name"], message_bodies)

        database.update_lead(
            lead_id,
            ai_score=result["score"],
            ai_summary=f"{result['reason']} | Action: {result['suggested_action']}"
        )

        return {
            "lead_id": lead_id,
            "score": result["score"],
            "reason": result["reason"],
            "intent": result["intent"],
            "suggested_action": result["suggested_action"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /leads/{lead_id}/score error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leads/{lead_id}/messages")
async def get_lead_messages(lead_id: int):
    try:
        lead = database.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        messages = database.get_messages_for_lead(lead_id)
        return {"messages": messages, "total": len(messages)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /leads/{lead_id}/messages error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leads/{lead_id}/send-message")
async def send_message_to_lead(lead_id: int, body: SendMessageRequest):
    try:
        lead = database.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        success = await whatsapp_bridge.send_message(lead["phone"], body.message)

        if success:
            database.save_message(lead["phone"], "outbound", body.message)
            database.update_lead(lead_id, last_contacted=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            return {"success": True, "message": "Message sent successfully"}
        else:
            raise HTTPException(status_code=503, detail="WhatsApp bridge unavailable — message not sent")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /leads/{lead_id}/send-message error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

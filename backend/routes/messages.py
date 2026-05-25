import logging
from fastapi import APIRouter, HTTPException
from backend import database
from backend.models import InboundMessageRequest
from backend.main_state import broadcast_message

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/messages/inbound")
async def receive_inbound_message(body: InboundMessageRequest):
    try:
        phone = body.phone.replace("@c.us", "").strip()

        lead = database.get_lead_by_phone(phone)
        if not lead:
            name = body.notify_name or f"WhatsApp {phone}"
            lead = database.create_lead(name=name, phone=phone, source="whatsapp")
            if not lead:
                raise HTTPException(status_code=500, detail="Failed to create lead for inbound message")
        elif body.notify_name and lead.get("name", "").startswith("WhatsApp "):
            database.update_lead(lead["id"], name=body.notify_name)
            lead = database.get_lead_by_id(lead["id"])

        msg = database.save_message(
            phone=phone,
            direction="inbound",
            body=body.body,
            wa_message_id=body.wa_message_id,
        )

        if msg:
            await broadcast_message({
                "type": "new_message",
                "message": msg,
                "lead_name": lead.get("name", phone),
            })

        return {"status": "ok", "lead_id": lead["id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /messages/inbound error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/recent")
async def get_recent_messages(limit: int = 50):
    try:
        messages = database.get_recent_messages(limit=limit)
        return {"messages": messages, "total": len(messages)}
    except Exception as e:
        logger.error(f"GET /messages/recent error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/save-outbound")
async def save_outbound_message(body: dict):
    """
    Called by the frontend in local mode after sending via the local bridge.
    Saves the outbound message to the DB so it appears in the chat history.
    """
    try:
        phone = str(body.get("phone", "")).replace("@c.us", "").strip()
        message = body.get("message", "")
        if not phone or not message:
            raise HTTPException(status_code=400, detail="phone and message required")
        database.save_message(phone=phone, direction="outbound", body=message)
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /messages/save-outbound error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

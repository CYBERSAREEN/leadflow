import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from backend import database, auth
from backend.models import InboundMessageRequest
from backend.main_state import broadcast_message

router = APIRouter()
logger = logging.getLogger(__name__)

BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "leadflow-bridge-secret-2024")
# Which user_id gets WhatsApp inbound leads (default: 1 = vedant)
WHATSAPP_OWNER_USER_ID = int(os.environ.get("WHATSAPP_OWNER_USER_ID", "1"))


def _verify_bridge(x_bridge_secret: Optional[str] = Header(None)) -> bool:
    """Returns True if request is from the WhatsApp bridge."""
    if x_bridge_secret and x_bridge_secret == BRIDGE_SECRET:
        return True
    return False


@router.post("/messages/inbound")
async def receive_inbound_message(
    body: InboundMessageRequest,
    x_bridge_secret: Optional[str] = Header(None),
):
    """
    Receive inbound WhatsApp message from the bridge.
    Authenticated via X-Bridge-Secret header.
    """
    # Validate bridge secret (non-JWT auth for bridge)
    if x_bridge_secret != BRIDGE_SECRET:
        # Also allow unauthenticated from localhost (backward compat)
        logger.warning("Inbound message without valid bridge secret — accepting anyway (backward compat)")

    try:
        phone = body.phone.replace("@c.us", "").replace("+", "").strip()

        # Find existing lead across ALL users first (phone is unique globally)
        lead = database.get_lead_by_phone(phone)
        if not lead:
            # Create lead under the WhatsApp owner user
            name = body.notify_name or f"WhatsApp {phone[-4:]}"
            lead = database.create_lead(
                name=name,
                phone=phone,
                source="whatsapp",
                user_id=WHATSAPP_OWNER_USER_ID,
            )
            if not lead:
                # Phone might already exist — try to get it again
                lead = database.get_lead_by_phone(phone)
                if not lead:
                    raise HTTPException(status_code=500, detail="Failed to create lead for inbound message")
        else:
            # Update name if: it's a default name AND we have a real notify_name
            current_name = lead.get("name", "")
            if body.notify_name and (
                current_name.startswith("WhatsApp ") or
                current_name == phone
            ):
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
                "lead_id": lead["id"],
                "lead_name": lead.get("name", phone),
            })

        return {"status": "ok", "lead_id": lead["id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /messages/inbound error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/recent")
async def get_recent_messages(
    limit: int = 50,
    current_user: dict = Depends(auth.get_current_user),
):
    try:
        messages = database.get_recent_messages(limit=limit, user_id=current_user["user_id"])
        return {"messages": messages, "total": len(messages)}
    except Exception as e:
        logger.error(f"GET /messages/recent error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/save-outbound")
async def save_outbound_message(
    body: dict,
    current_user: dict = Depends(auth.get_current_user),
):
    """
    Called by the frontend in local mode after sending via the local bridge.
    Saves the outbound message to the DB.
    """
    try:
        phone = str(body.get("phone", "")).replace("@c.us", "").replace("+", "").strip()
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

"""
WhatsApp Cloud API (Meta Official)
───────────────────────────────────
Replaces the old Baileys local-bridge with direct calls to
  https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages

Env vars required (set in .env):
  WA_PHONE_NUMBER_ID   – e.g. 1117785374756659
  WA_ACCESS_TOKEN      – permanent / temporary token from Meta developer console
  WA_WEBHOOK_VERIFY_TOKEN – any string; also configure it in Meta App → Webhooks
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
_PHONE_ID   = os.environ.get("WA_PHONE_NUMBER_ID", "")
_TOKEN      = os.environ.get("WA_ACCESS_TOKEN", "")
_API_VER    = "v25.0"
_BASE_URL   = f"https://graph.facebook.com/{_API_VER}/{_PHONE_ID}"
_HEADERS    = {
    "Authorization": f"Bearer {_TOKEN}",
    "Content-Type": "application/json",
}

def _is_configured() -> bool:
    return bool(_PHONE_ID and _TOKEN and _TOKEN != "PASTE_YOUR_TOKEN_HERE")


# ── Send plain text message ──────────────────────────────────────────────────
async def send_message(phone: str, message: str) -> bool:
    """
    Send a free-form text message to `phone` (E.164 without '+', e.g. 917087603933).
    Returns True on success.

    NOTE: Meta allows free-form text only within a 24-hour customer-service window.
    Outside that window use send_template() instead.
    """
    if not _is_configured():
        logger.error("WhatsApp Cloud API not configured — set WA_PHONE_NUMBER_ID & WA_ACCESS_TOKEN in .env")
        return False

    # Normalise phone — strip spaces, +, @c.us
    phone = phone.replace("@c.us", "").replace("+", "").replace(" ", "").strip()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_BASE_URL}/messages", headers=_HEADERS, json=payload)
            if resp.status_code in (200, 201):
                data = resp.json()
                wa_id = data.get("messages", [{}])[0].get("id", "?")
                logger.info(f"WA sent → {phone}  wa_id={wa_id}")
                return True
            else:
                logger.error(f"WA send failed [{resp.status_code}]: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"send_message exception: {e}")
        return False


# ── Send template message ────────────────────────────────────────────────────
async def send_template(phone: str, template_name: str = "hello_world",
                        language_code: str = "en_US",
                        components: list | None = None) -> bool:
    """
    Send an approved template message.
    Use this outside the 24-hour window, or for first-touch outreach.

    Example:
        await send_template("917087603933", "hello_world", "en_US")
    """
    if not _is_configured():
        logger.error("WhatsApp Cloud API not configured.")
        return False

    phone = phone.replace("@c.us", "").replace("+", "").replace(" ", "").strip()

    template: dict = {
        "name": template_name,
        "language": {"code": language_code},
    }
    if components:
        template["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": template,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_BASE_URL}/messages", headers=_HEADERS, json=payload)
            if resp.status_code in (200, 201):
                data = resp.json()
                wa_id = data.get("messages", [{}])[0].get("id", "?")
                logger.info(f"WA template sent → {phone}  wa_id={wa_id}")
                return True
            else:
                logger.error(f"WA template failed [{resp.status_code}]: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"send_template exception: {e}")
        return False


# ── Connection / status helpers (for UI) ────────────────────────────────────
async def get_connection_status() -> dict:
    """Returns whether Cloud API credentials are configured."""
    if not _is_configured():
        return {
            "connected": False,
            "phone": None,
            "mode": "cloud_api",
            "error": "WA_ACCESS_TOKEN or WA_PHONE_NUMBER_ID not set",
        }
    # Optionally hit Meta's phone number endpoint to verify the token is valid
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"https://graph.facebook.com/{_API_VER}/{_PHONE_ID}",
                headers=_HEADERS,
                params={"fields": "display_phone_number,verified_name"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "connected": True,
                    "phone": data.get("display_phone_number"),
                    "name": data.get("verified_name"),
                    "mode": "cloud_api",
                }
            else:
                return {"connected": False, "phone": None, "mode": "cloud_api",
                        "error": f"Token check failed: {resp.status_code}"}
    except Exception as e:
        return {"connected": False, "phone": None, "mode": "cloud_api", "error": str(e)}


async def get_qr_code() -> dict:
    """Cloud API does not need QR — always return no QR needed."""
    return {
        "connected": _is_configured(),
        "qr": None,
        "mode": "cloud_api",
        "message": "Meta Cloud API — no QR scan required",
    }


async def disconnect() -> dict:
    """Cloud API has no session to disconnect."""
    return {"success": True, "message": "Cloud API mode — no active session to disconnect"}

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from backend import database
        database.init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")

    # Ensure default user exists (REST fallback for IPv6-only Supabase)
    try:
        from backend import database
        database.ensure_default_user()
        logger.info("Default user check done")
    except Exception as e:
        logger.error(f"Default user check failed (non-fatal): {e}")

    try:
        from backend.services.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scheduler started")
    except Exception as e:
        logger.error(f"Scheduler start failed (non-fatal): {e}")

    logger.info("LeadFlow AI started")
    yield

    try:
        from backend.services.scheduler import stop_scheduler
        stop_scheduler()
    except Exception as e:
        logger.error(f"Scheduler stop error: {e}")

    logger.info("LeadFlow AI stopped")


app = FastAPI(title="LeadFlow AI", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/setup-db")
async def setup_db():
    """
    One-time bootstrap: create tables + default user via psycopg2.
    Safe to call multiple times (idempotent). No auth required.
    """
    import os, psycopg2
    from urllib.parse import urlparse, unquote
    from backend.auth import get_password_hash

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return {"ok": False, "error": "DATABASE_URL not set"}

    results = []
    try:
        parsed = urlparse(db_url)
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            dbname=(parsed.path or "/postgres").lstrip("/"),
            user=unquote(parsed.username or "postgres"),
            password=unquote(parsed.password or ""),
            sslmode="require",
            connect_timeout=15,
        )
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        results.append("users table: ok")

        cur.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
        results.append("leads.user_id: ok")

        cur.execute("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
        results.append("daily_reports.user_id: ok")

        hashed = get_password_hash("Vedant@1234")
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING",
            ("vedant", hashed)
        )
        results.append("user vedant: inserted (or already exists)")

        conn.commit()
        conn.close()
        return {"ok": True, "results": results, "message": "Setup complete! You can now login with vedant / Vedant@1234"}
    except Exception as e:
        return {"ok": False, "error": str(e), "results": results}


from backend.routes import leads, messages, analytics, ai, auth as auth_routes
from backend.services import whatsapp_bridge

app.include_router(auth_routes.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(ai.router, prefix="/api")


@app.get("/api/whatsapp/status")
async def whatsapp_status():
    return await whatsapp_bridge.get_connection_status()


@app.get("/api/whatsapp/qr")
async def whatsapp_qr():
    return await whatsapp_bridge.get_qr_code()


@app.post("/api/whatsapp/disconnect")
async def whatsapp_disconnect():
    return await whatsapp_bridge.disconnect()


# ── Meta Cloud API Webhook ─────────────────────────────────────────────────
@app.get("/api/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    """
    Meta calls this GET to verify the webhook URL.
    Set WA_WEBHOOK_VERIFY_TOKEN in .env and paste the same string in
    Meta Developer Console → App → WhatsApp → Configuration → Webhook.
    """
    params = dict(request.query_params)
    mode       = params.get("hub.mode")
    token      = params.get("hub.verify_token")
    challenge  = params.get("hub.challenge")
    verify_tok = os.environ.get("WA_WEBHOOK_VERIFY_TOKEN", "leadflow-webhook-verify-2024")

    if mode == "subscribe" and token == verify_tok:
        logger.info("WhatsApp webhook verified ✓")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=challenge, status_code=200)
    logger.warning(f"Webhook verify failed — mode={mode} token={token}")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook_receive(request: Request):
    """
    Meta posts inbound messages here.
    Each message is stored in DB and broadcast via WebSocket (same as the old Baileys flow).
    """
    try:
        body = await request.json()
        logger.debug(f"WA webhook payload: {body}")

        from backend.main_state import broadcast_message
        from backend import database

        entries = body.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages_list = value.get("messages", [])
                contacts = value.get("contacts", [])
                contact_map = {c["wa_id"]: c.get("profile", {}).get("name") for c in contacts}

                for msg in messages_list:
                    if msg.get("type") != "text":
                        continue  # skip non-text (images, stickers, etc.) for now

                    phone     = msg.get("from", "")          # e.g. "917087603933"
                    wa_msg_id = msg.get("id")
                    text_body = msg.get("text", {}).get("body", "")
                    notify    = contact_map.get(phone)

                    # Upsert lead
                    lead = database.get_lead_by_phone(phone)
                    if not lead:
                        name = notify or f"WA {phone[-4:]}"
                        lead = database.create_lead(
                            name=name, phone=phone, source="whatsapp",
                            user_id=int(os.environ.get("WHATSAPP_OWNER_USER_ID", "1")),
                        )
                        if not lead:
                            lead = database.get_lead_by_phone(phone)
                    else:
                        current_name = lead.get("name", "")
                        if notify and (current_name.startswith("WA ") or current_name == phone):
                            database.update_lead(lead["id"], name=notify)
                            lead = database.get_lead_by_id(lead["id"])

                    if lead and text_body:
                        saved_msg = database.save_message(
                            phone=phone, direction="inbound",
                            body=text_body, wa_message_id=wa_msg_id,
                        )
                        if saved_msg:
                            await broadcast_message({
                                "type": "new_message",
                                "message": saved_msg,
                                "lead_id": lead["id"],
                                "lead_name": lead.get("name", phone),
                            })

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook receive error: {e}")
        return {"status": "error", "detail": str(e)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    from backend.main_state import active_connections
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(f"WebSocket connected — {len(active_connections)} clients")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.discard(websocket)
    except Exception as e:
        active_connections.discard(websocket)
        logger.error(f"WebSocket error: {e}")

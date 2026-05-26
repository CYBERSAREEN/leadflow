import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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

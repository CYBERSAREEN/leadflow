import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend import database
    from backend.services.scheduler import start_scheduler, stop_scheduler
    database.init_db()
    start_scheduler()
    logger.info("LeadFlow AI started")
    yield
    stop_scheduler()
    logger.info("LeadFlow AI stopped")


app = FastAPI(title="LeadFlow AI", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routes import leads, messages, analytics, ai
from backend.services import whatsapp_bridge

app.include_router(leads.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(ai.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}


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
        logger.info(f"WebSocket disconnected — {len(active_connections)} clients")
    except Exception as e:
        active_connections.discard(websocket)
        logger.error(f"WebSocket error: {e}")


frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

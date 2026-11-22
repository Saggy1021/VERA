# FILE: backend/main.py
# FastAPI app entry, socket.io mount

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx

from config import settings
from database import init_db_pool, close_db_pool
from routers import sessions, candidates, events, reports, audit, health
from websocket.handlers import register_socketio_events

# ── Socket.IO ─────────────────────────────────
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
register_socketio_events(sio)

# ── Shared HTTP client (reused across requests) ─
http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    # STARTUP: fast — no model loading
    await init_db_pool(settings.database_url)
    http_client = httpx.AsyncClient(timeout=30.0)
    app.state.http_client = http_client
    yield
    # SHUTDOWN
    await close_db_pool()
    await http_client.aclose()


app = FastAPI(
    title='SENTINEL API',
    version='1.0.0',
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# ── Register REST routers ──────────────────────
app.include_router(health.router, tags=['health'])
app.include_router(sessions.router, prefix='/api', tags=['sessions'])
app.include_router(candidates.router, prefix='/api', tags=['candidates'])
app.include_router(events.router, prefix='/api', tags=['events'])
app.include_router(reports.router, prefix='/api', tags=['reports'])
app.include_router(audit.router, prefix='/api', tags=['audit'])

# ── Mount Socket.IO on /socket.io ─────────────
socket_app = socketio.ASGIApp(sio, app)

# Run with: uvicorn main:socket_app --host 0.0.0.0 --port 8000 --workers 2

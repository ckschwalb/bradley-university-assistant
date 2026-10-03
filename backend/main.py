#!/usr/bin/env python3
"""
Bradley University AI Assistant - Main FastAPI Application

Wires the app together: CORS and the cross-site write guard, the routers (chat, admin, settings and
the rest in routers/), and the React build. Answering lives in answering.py and routers/chat.py;
crawling runs separately in crawler_service.py.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from db import init_db
from llm import active_selection
from routers.admin import router as admin_router
from routers.chat import router as chat_router
from routers.conversations import router as conversations_router
from routers.feedback import router as feedback_router
from routers.observability import router as observability_router
from routers.settings import router as settings_router
from routers.suggestions import router as suggestions_router
from routers.system import router as system_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    selection = active_selection()
    logger.info(f"AI provider: {selection['provider'] + ' / ' + selection['model'] if selection else 'not configured'}")
    yield


app = FastAPI(title="Bradley University AI Assistant", version="1.0.0", lifespan=lifespan)

# The app itself, reached as localhost or 127.0.0.1, plus the React dev server
allowed_origins = sorted({
    PUBLIC_BASE_URL,
    PUBLIC_BASE_URL.replace("localhost", "127.0.0.1"),
    PUBLIC_BASE_URL.replace("127.0.0.1", "localhost"),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
})

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    """The admin API has no password unless ADMIN_TOKEN is set (the app only listens on this machine),
    so refuse state-changing requests sent by other websites open in the same browser."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Cross-site request refused"})
    return await call_next(request)


app.include_router(system_router)
app.include_router(chat_router)
app.include_router(feedback_router)
app.include_router(admin_router)
app.include_router(settings_router)
app.include_router(conversations_router)
app.include_router(suggestions_router)
app.include_router(observability_router)

# The React production build (frontend/build), copied here by the Dockerfile
frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
assets_dir = os.path.join(frontend_dir, "static")
if os.path.isdir(assets_dir):
    app.mount("/static", StaticFiles(directory=assets_dir), name="static")

# Catch-all route for React Router (must be last)
@app.get("/{path:path}")
async def catch_all(path: str):
    """Serve the React app for client-side routes"""
    if path.startswith(("api/", "chat", "health")):
        raise HTTPException(status_code=404, detail="Not found")
    # Top-level build files such as background.jpg
    file_path = os.path.realpath(os.path.join(frontend_dir, path))
    if path and file_path.startswith(os.path.realpath(frontend_dir) + os.sep) and os.path.isfile(file_path):
        return FileResponse(file_path)
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Bradley University AI Assistant API. Build the frontend to serve the UI here."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", 8000)))

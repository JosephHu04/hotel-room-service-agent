"""
Hotel Room Service Agent — FastAPI Production Server
====================================================
Standard HTTP interface for the Main Router Agent to call.

Startup:
    python server.py
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    POST /api/chat          — Chat endpoint (core)
    GET  /api/health        — Health check
    GET  /api/sessions      — Active session list
    DELETE /api/sessions/{id} — Clear session (guest checkout)
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from room_service_agent import invoke_agent, invoke_agent_structured, clear_session
from tools_api.mock_services import ALL_TOOLS

# ==========================================
# Logging
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] Server - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("HotelServer")

# ==========================================
# Data Models
# ==========================================

class ChatRequest(BaseModel):
    """Chat request"""
    message: str = Field(..., description="Guest message", min_length=1, max_length=2000)
    session_id: str = Field(
        default="default",
        description="Session identifier. Use room number, e.g. '301'. Same session_id shares conversation memory."
    )

class ChatResponse(BaseModel):
    """Chat response — ReAct Agent version"""
    response: str = Field(..., description="Agent's natural language reply")
    session_id: str = Field(..., description="Session identifier (echoed back)")

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    agent: str
    model: str
    tools: list[str]

class SessionInfo(BaseModel):
    """Session info"""
    session_id: str


# ==========================================
# FastAPI App & Lifespan
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks"""
    logger.info("=" * 50)
    logger.info("🏨 Hotel Room Service Agent starting")
    logger.info("   Model: deepseek-chat (DeepSeek API)")
    logger.info("   Tools: %s", [t.name for t in ALL_TOOLS])
    logger.info("=" * 50)
    yield
    logger.info("Agent server shut down")

app = FastAPI(
    title="Hotel Room Service Agent",
    description="Hotel room service agent — supports cleaning, supplies, maintenance, laundry, wake-up calls, front desk calls",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the Main Router to call from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# API Endpoints
# ==========================================

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Core chat endpoint.

    The Main Router POSTs the guest's message to this endpoint.
    The Agent decides based on content: reply directly, or call tools to perform actions.

    Supports multi-turn conversation: pass the same session_id to maintain dialogue context.
    """
    logger.info("Session[%s] received: %s", request.session_id, request.message[:100])

    try:
        structured = invoke_agent_structured(
            message=request.message,
            session_id=request.session_id,
        )
    except Exception as e:
        logger.error("Session[%s] processing failed: %s", request.session_id, str(e))
        raise HTTPException(status_code=500, detail="Internal processing error, please try again later")

    return ChatResponse(
        response=structured.get("response_text", ""),
        session_id=request.session_id,
    )


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """
    Health check endpoint.

    Called by the Main Router on startup to confirm the Room Service Agent is online.
    Can also be used by monitoring systems for periodic probing.
    """
    return HealthResponse(
        status="ok",
        agent="RoomServiceAgent",
        model="deepseek-chat",
        tools=[t.name for t in ALL_TOOLS],
    )


@app.get("/api/sessions")
async def list_sessions():
    """
    List currently active sessions (simplified).

    In production, should return the actual thread list from MemorySaver.
    """
    return {
        "message": "Sessions are stored in memory in MemorySaver mode and cleared on restart",
        "note": "Upgrade to SqliteSaver for persistent session querying",
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Clear conversation history for a given session.

    After guest checkout, the front desk system should call this endpoint
    to wipe that room's conversation memory, protecting guest privacy.
    """
    clear_session(session_id)
    logger.info("Session[%s] manually cleared (checkout)", session_id)
    return {"status": "ok", "message": f"Session {session_id} cleared"}


# ==========================================
# Direct run
# ==========================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[os.path.join(os.path.dirname(__file__))],
        log_level="info",
    )

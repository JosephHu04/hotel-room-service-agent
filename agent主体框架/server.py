"""
酒店客房服务 Agent — FastAPI 服务器
=============================================
启动方式:
    python server.py

接口:
    POST   /api/chat             — 对话接口
    GET    /api/health           — 健康检查
    GET    /api/sessions         — 活跃会话列表
    DELETE /api/sessions/{id}    — 清除会话（退房）
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
# 日志
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] Server - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("HotelServer")

# ==========================================
# 数据模型
# ==========================================

class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., description="客人消息", min_length=1, max_length=2000)
    session_id: str = Field(
        default="default",
        description="会话标识，建议用房间号，如 '301'。同 session_id 共享对话记忆。"
    )

class ChatResponse(BaseModel):
    """对话响应 — ReAct Agent 版本"""
    response: str = Field(..., description="Agent 的自然语言回复")
    session_id: str = Field(..., description="会话标识（回传）")
    tool_calls: list[dict] = Field(default_factory=list, description="本轮调用的工具列表")

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    agent: str
    model: str
    tools: list[str]

# ==========================================
# FastAPI 应用 & 生命周期
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭时的钩子"""
    logger.info("=" * 50)
    logger.info("🏨 酒店客房服务 Agent 启动")
    logger.info("   模型: qwen3:8b (Ollama 本地)")
    logger.info("   工具: %s", [t.name for t in ALL_TOOLS])
    logger.info("=" * 50)
    yield
    logger.info("Agent 服务器已关闭")

app = FastAPI(
    title="Hotel Room Service Agent",
    description="酒店客房服务智能体 — 支持清扫、补给、报修、洗衣、唤醒、呼叫前台",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — 允许总控 Agent 从任何来源调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# API 端点
# ==========================================

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    核心对话接口。

    总控 Agent (MainRouter) 将客人的消息 POST 到此端点，
    Agent 根据消息内容决定：直接回答、或调用工具执行实际操作。

    支持多轮对话：传入相同的 session_id 可保持对话上下文。
    """
    logger.info("会话[%s] 收到: %s", request.session_id, request.message[:100])

    try:
        structured = invoke_agent_structured(
            message=request.message,
            session_id=request.session_id,
        )
    except Exception as e:
        logger.error("会话[%s] 处理失败: %s", request.session_id, str(e))
        raise HTTPException(status_code=500, detail="内部处理错误，请稍后重试")

    return ChatResponse(
        response=structured.get("response_text", ""),
        session_id=request.session_id,
        tool_calls=structured.get("tool_calls", []),
    )


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """
    健康检查接口。

    总控 Agent 启动时调用此接口确认客房服务 Agent 在线。
    也可用于监控系统定期探测。
    """
    return HealthResponse(
        status="ok",
        agent="RoomServiceAgent",
        model="qwen3:8b (Ollama 本地)",
        tools=[t.name for t in ALL_TOOLS],
    )


@app.get("/api/sessions")
async def list_sessions():
    """
    列出当前活跃会话（简化版）。

    生产环境应返回实际 MemorySaver 中的 thread 列表。
    """
    return {
        "message": "MemorySaver 模式下会话存储在内存中，重启后自动清除",
        "note": "升级为 SqliteSaver 后可查询持久化会话列表",
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    清除指定会话的对话历史。

    客人退房后，前台系统应调用此接口清除该房间的对话记忆，
    以保护客人隐私。
    """
    clear_session(session_id)
    logger.info("会话[%s] 已手动清除（退房操作）", session_id)
    return {"status": "ok", "message": f"会话 {session_id} 已清除"}


# ==========================================
# 直接运行
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

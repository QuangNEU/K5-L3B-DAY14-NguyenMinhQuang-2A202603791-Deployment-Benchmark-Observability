"""
Production AI Agent — Part 6 Final Project
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Format mỗi dòng log thành 1 JSON object hợp lệ để log aggregator parse dễ dàng."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("event", "path", "method", "status", "ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return logging.getLogger("agent")


logger = _setup_logging()

_in_flight_requests = 0
_is_shutting_down = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời app: khởi động và graceful shutdown khi nhận SIGTERM."""
    global _is_shutting_down
    logger.info("Agent starting up", extra={"event": "startup"})
    yield

    _is_shutting_down = True
    logger.info("Graceful shutdown initiated", extra={"event": "shutdown_start"})

    deadline = time.monotonic() + 8.0
    while _in_flight_requests > 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.05)

    logger.info("Graceful shutdown complete", extra={"event": "shutdown_complete"})


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Không để lộ stack trace ra response khi có lỗi ngoài ý muốn."""
    logger.error("Unhandled error on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.middleware("http")
async def log_and_track_requests(request: Request, call_next):
    """Đếm request đang xử lý (phục vụ graceful shutdown) và ghi access log dạng JSON."""
    global _in_flight_requests
    _in_flight_requests += 1
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        _in_flight_requests -= 1
        logger.info(
            "http_request",
            extra={
                "event": "request",
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "ms": elapsed_ms,
            },
        )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn chạy, kể cả khi Redis mất kết nối."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness probe: 200 khi sẵn sàng, 503 khi đang shutdown hoặc Redis mất kết nối."""
    if _is_shutting_down or not redis_healthy():
        raise HTTPException(status_code=503, detail="Service not ready")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost = record_cost(input_tokens, output_tokens)

    return {
        "question": body.question,
        "answer": answer,
        "cost_usd": round(cost, 6),
    }

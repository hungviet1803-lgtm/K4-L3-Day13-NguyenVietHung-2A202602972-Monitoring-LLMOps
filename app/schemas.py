from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(..., examples=["u_student_01"])
    session_id: str = Field(..., examples=["s_demo_01"])
    feature: str = Field(default="qa", examples=["qa", "summary"])
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    answer: str
    correlation_id: str
    latency_ms: int
    ttft_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float
    trace_id: str | None = None
    prompt_version: str | None = None


class LogRecord(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: Literal["info", "warning", "error", "critical"]
    service: str
    event: str
    correlation_id: str
    trace_id: str | None = None
    env: str
    user_id_hash: str | None = None
    session_id: str | None = None
    feature: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    ttft_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error_type: str | None = None
    tool_name: str | None = None
    tool_success: bool | None = None
    payload: dict[str, Any] | None = None

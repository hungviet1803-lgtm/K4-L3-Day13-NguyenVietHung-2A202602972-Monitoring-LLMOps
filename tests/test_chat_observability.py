from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx

from app import logging_config
from app.main import app


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/chat",
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Explain observability",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert response_event["quality_score"] == response.json()["quality_score"]
    assert response_event["ttft_ms"] == response.json()["ttft_ms"]
    assert response_event["tool_name"] == "retrieval"
    assert response_event["tool_success"] is True


def test_chat_sets_correlation_headers_and_scrubs_logs(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send(headers: dict[str, str]) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/chat",
                headers=headers,
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "My email is student@vinuni.edu.vn and phone 0987654321",
                },
            )

    generated = asyncio.run(send({}))
    assert generated.headers["x-request-id"].startswith("req-")
    assert len(generated.headers["x-request-id"]) == 12
    assert float(generated.headers["x-response-time-ms"]) >= 0
    assert generated.json()["correlation_id"] == generated.headers["x-request-id"]

    forwarded = asyncio.run(send({"x-request-id": "client-abc-123"}))
    assert forwarded.headers["x-request-id"] == "client-abc-123"

    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "0987654321" not in raw
    assert "student-01" not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    received = [e for e in events if e["event"] == "request_received"]
    assert {e["correlation_id"] for e in received} == {
        generated.headers["x-request-id"],
        "client-abc-123",
    }
    for event in received:
        for field in ("user_id_hash", "session_id", "feature", "model", "env"):
            assert field in event

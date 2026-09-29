from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import dashboard, logging_config


def _write(path: Path, now: datetime) -> None:
    ts = lambda m: (now - timedelta(minutes=m)).isoformat().replace("+00:00", "Z")  # noqa: E731
    rows = [
        {"ts": ts(5), "event": "request_received"},
        {"ts": ts(5), "event": "response_sent", "latency_ms": 800, "ttft_ms": 50, "cost_usd": 0.002,
         "tokens_in": 30, "tokens_out": 120, "quality_score": 0.8, "tool_success": True},
        {"ts": ts(3), "event": "request_received"},
        {"ts": ts(3), "event": "request_failed", "error_type": "RuntimeError", "tool_success": False},
        {"ts": ts(90), "event": "request_received"},  # outside the 60-minute window
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_dashboard_computes_contract_aggregations(monkeypatch, tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    log_path = tmp_path / "logs.jsonl"
    _write(log_path, now)
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    data = dashboard.compute_panels(dashboard.load_events(60, now), 60)

    assert data["traffic"]["stats"]["count"] == 2
    assert data["errors"]["stats"]["error_rate_pct"] == 50.0
    assert data["errors"]["stats"]["tool_success_rate_pct"] == 50.0
    assert data["errors"]["breakdown"] == {"RuntimeError": 1}
    assert data["latency"]["stats"]["p95"] == 800
    assert data["tokens"]["stats"]["tokens_out"] == 120

    html = dashboard.render_dashboard(now)
    for title in ("Latency percentiles and TTFT", "Request traffic", "Error rate and retrieval success",
                  "Cost over time", "Input and output tokens", "Quality proxy"):
        assert title in html
    assert "last 60 minutes" in html
    assert "BREACH" in html  # 50% error rate breaches the 2% SLO

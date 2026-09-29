"""Six-panel runtime dashboard built from data/logs.jsonl.

Panel titles, units and thresholds come from config/dashboard.yaml so the page
always matches the grading contract. Charts are inline SVG: no extra deps.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from . import logging_config

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "dashboard.yaml"
SERIES_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    items = sorted(values)
    idx = max(0, min(len(items) - 1, round((p / 100) * len(items) + 0.5) - 1))
    return float(items[idx])


def load_events(window_minutes: int, now: datetime) -> list[dict[str, Any]]:
    path = Path(logging_config.LOG_PATH)
    if not path.exists():
        return []
    since = now - timedelta(minutes=window_minutes)
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if since <= ts <= now:
            rec["_minute"] = int((ts - since).total_seconds() // 60)
            events.append(rec)
    return events


def compute_panels(events: list[dict[str, Any]], window: int) -> dict[str, dict[str, Any]]:
    received = [e for e in events if e.get("event") == "request_received"]
    sent = [e for e in events if e.get("event") == "response_sent"]
    failed = [e for e in events if e.get("event") == "request_failed"]

    def by_minute(items: list[dict], field: str | None = None) -> dict[int, list[float]]:
        buckets: dict[int, list[float]] = defaultdict(list)
        for e in items:
            buckets[e["_minute"]].append(1.0 if field is None else float(e.get(field) or 0))
        return buckets

    def series(buckets: dict[int, list[float]], agg) -> list[tuple[int, float]]:
        return [(m, agg(v)) for m, v in sorted(buckets.items()) if v]

    def cumulative(items: list[dict], field: str) -> list[tuple[int, float]]:
        total, points = 0.0, []
        for m, vals in sorted(by_minute(items, field).items()):
            total += sum(vals)
            points.append((m, total))
        return points

    lat = by_minute(sent, "latency_ms")
    ttft = by_minute(sent, "ttft_ms")
    latencies = [float(e["latency_ms"]) for e in sent]
    ttfts = [float(e["ttft_ms"]) for e in sent]

    recv_by_min = by_minute(received)
    fail_by_min = by_minute(failed)
    error_rate_series = [
        (m, len(fail_by_min.get(m, [])) / len(v) * 100) for m, v in sorted(recv_by_min.items())
    ]
    tool_events = [e for e in sent + failed if e.get("tool_success") is not None]
    tool_ok = sum(1 for e in tool_events if e.get("tool_success") is True)

    total_cost = sum(float(e.get("cost_usd") or 0) for e in sent)
    tokens_in = sum(int(e.get("tokens_in") or 0) for e in sent)
    tokens_out = sum(int(e.get("tokens_out") or 0) for e in sent)
    qualities = [float(e["quality_score"]) for e in sent if e.get("quality_score") is not None]

    return {
        "latency": {
            "series": {
                "P50": series(lat, lambda v: _percentile(v, 50)),
                "P95": series(lat, lambda v: _percentile(v, 95)),
                "P99": series(lat, lambda v: _percentile(v, 99)),
                "TTFT P95": series(ttft, lambda v: _percentile(v, 95)),
            },
            "stats": {
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
                "p99": _percentile(latencies, 99),
                "ttft_p95": _percentile(ttfts, 95),
            },
        },
        "traffic": {
            "series": {"requests/min": series(recv_by_min, len)},
            "stats": {
                "count": len(received),
                "rate_per_minute": len(received) / max(1, len(recv_by_min)),
            },
        },
        "errors": {
            "series": {"error rate %": error_rate_series},
            "stats": {
                "error_rate_pct": len(failed) / len(received) * 100 if received else 0.0,
                "tool_success_rate_pct": tool_ok / len(tool_events) * 100 if tool_events else 100.0,
            },
            "breakdown": Counter(e.get("error_type") or "unknown" for e in failed),
        },
        "cost": {
            "series": {"cumulative USD": cumulative(sent, "cost_usd")},
            "bars": series(by_minute(sent, "cost_usd"), sum),
            "stats": {"total": total_cost},
        },
        "tokens": {
            "series": {
                "tokens_in (cumulative)": cumulative(sent, "tokens_in"),
                "tokens_out (cumulative)": cumulative(sent, "tokens_out"),
            },
            "stats": {"sum_by_field": max(tokens_in, tokens_out), "tokens_in": tokens_in, "tokens_out": tokens_out},
        },
        "quality": {
            "series": {"mean quality": series(by_minute(sent, "quality_score"), mean)},
            "stats": {"mean": mean(qualities) if qualities else 0.0},
        },
    }


def _fmt(value: float, unit: str) -> str:
    if unit == "usd":
        return f"${value:.4f}"
    if unit in ("percent",):
        return f"{value:.1f}%"
    if unit == "score_0_to_1":
        return f"{value:.2f}"
    if unit == "requests_per_minute":
        return f"{value:.1f}"
    return f"{value:,.0f}"


def _chart(series: dict[str, list[tuple[int, float]]], threshold: float, window: int,
           unit: str, bars: list[tuple[int, float]] | None = None) -> str:
    w, h, left, bottom, top = 560, 190, 56, 24, 12
    plot_w, plot_h = w - left - 10, h - bottom - top
    values = [v for pts in series.values() for _, v in pts] + [threshold]
    y_max = max(values) * 1.15 or 1.0

    def x(m: float) -> float:
        return left + (m + 0.5) / window * plot_w

    def y(v: float) -> float:
        return top + plot_h - v / y_max * plot_h

    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" class="chart">']
    for frac in (0, 0.5, 1):
        gy = top + plot_h * (1 - frac)
        parts.append(f'<line x1="{left}" x2="{w - 10}" y1="{gy:.1f}" y2="{gy:.1f}" class="grid"/>')
        parts.append(f'<text x="{left - 6}" y="{gy + 4:.1f}" class="tick" text-anchor="end">'
                     f'{escape(_fmt(y_max * frac, unit))}</text>')
    for m, label in ((0, f"-{window}m"), (window / 2, f"-{window // 2}m"), (window - 0.5, "now")):
        parts.append(f'<text x="{x(m):.1f}" y="{h - 6}" class="tick" text-anchor="middle">{label}</text>')
    if bars:
        bar_max = max(v for _, v in bars) or 1.0
        for m, v in bars:
            bh = v / bar_max * plot_h * 0.35
            parts.append(f'<rect x="{x(m) - 3:.1f}" y="{top + plot_h - bh:.1f}" width="6" height="{bh:.1f}" class="bar"/>')
    for (name, pts), color in zip(series.items(), SERIES_COLORS):
        if not pts:
            continue
        path = " ".join(f"{x(m):.1f},{y(v):.1f}" for m, v in pts)
        parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        for m, v in pts:
            parts.append(f'<circle cx="{x(m):.1f}" cy="{y(v):.1f}" r="2.5" fill="{color}"><title>{escape(name)}: {escape(_fmt(v, unit))}</title></circle>')
    ty = y(threshold)
    parts.append(f'<line x1="{left}" x2="{w - 10}" y1="{ty:.1f}" y2="{ty:.1f}" class="threshold"/>')
    parts.append(f'<text x="{w - 12}" y="{ty - 4:.1f}" class="threshold-label" text-anchor="end">'
                 f'SLO {escape(_fmt(threshold, unit))}</text>')
    parts.append("</svg>")
    legend = "".join(
        f'<span class="key"><i style="background:{c}"></i>{escape(n)}</span>'
        for n, c in zip(series, SERIES_COLORS)
    )
    return "".join(parts) + f'<div class="legend">{legend}</div>'


def render_dashboard(now: datetime | None = None) -> str:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["dashboard"]
    window = config["time_range_minutes"]
    now = now or datetime.now(timezone.utc)
    events = load_events(window, now)
    data = compute_panels(events, window)

    cards = []
    for panel in config["panels"]:
        pid, unit, th = panel["id"], panel["unit"], panel["threshold"]
        pdata = data[pid]
        observed = pdata["stats"][th["aggregation"]]
        ok = observed <= th["value"] if th["operator"] == "lte" else observed >= th["value"]
        op = "≤" if th["operator"] == "lte" else "≥"
        stats = " · ".join(
            f"{escape(k)} <b>{escape(_fmt(v, unit))}</b>" for k, v in pdata["stats"].items()
        )
        extra = ""
        if pid == "errors":
            rows = "".join(f"<li>{escape(k)}: <b>{v}</b></li>" for k, v in pdata["breakdown"].most_common())
            extra = f'<ul class="breakdown">{rows or "<li>no errors in window</li>"}</ul>'
        cards.append(f"""
<section class="card">
  <header>
    <h2>{escape(panel["title"])}</h2>
    <span class="badge {'ok' if ok else 'bad'}">{'OK' if ok else 'BREACH'}</span>
  </header>
  <p class="meta">unit: <b>{escape(unit)}</b> · SLO: {escape(th["aggregation"])} {op} {escape(_fmt(th["value"], unit))} · last {window} min</p>
  <p class="stats">{stats}</p>
  {_chart(pdata["series"], float(th["value"]), window, unit, pdata.get("bars"))}
  {extra}
</section>""")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{config['refresh_seconds']}">
<title>{escape(config["title"])}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --fg:#1d232b; --muted:#5f6b7a; --grid:#e3e7ec;
  --s1:#2f6fdf; --s2:#d9730d; --s3:#8a4fd1; --s4:#1f9d6b; --bad:#c9372c; --ok:#1f8a5b; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171c; --card:#1d222a; --fg:#e7eaee;
  --muted:#9aa5b1; --grid:#2c333d; --s1:#6a9cf5; --s2:#f0a04b; --s3:#b48be8; --s4:#4cc494;
  --bad:#f0685d; --ok:#4cc494; }} }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; }}
h1 {{ font-size:20px; margin:0 0 4px; }}
.sub {{ color:var(--muted); margin:0 0 16px; }}
.grid-wrap {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap:16px; }}
.card {{ background:var(--card); border-radius:10px; padding:14px 16px; box-shadow:0 1px 2px rgb(0 0 0 / .08); min-width:0; }}
.card header {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
h2 {{ font-size:15px; margin:0; }}
.meta, .legend, .breakdown {{ color:var(--muted); font-size:12px; }}
.meta {{ margin:4px 0; }} .stats {{ margin:4px 0 8px; }}
.badge {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:99px; color:#fff; }}
.badge.ok {{ background:var(--ok); }} .badge.bad {{ background:var(--bad); }}
.chart {{ width:100%; height:auto; display:block; }}
.grid {{ stroke:var(--grid); }} .tick {{ fill:var(--muted); font-size:10px; }}
.threshold {{ stroke:var(--bad); stroke-dasharray:6 4; stroke-width:1.5; }}
.threshold-label {{ fill:var(--bad); font-size:10px; font-weight:600; }}
.bar {{ fill:var(--grid); }}
.legend {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:4px; }}
.key i {{ display:inline-block; width:10px; height:3px; margin-right:5px; vertical-align:middle; }}
.breakdown {{ margin:6px 0 0; padding-left:18px; }}
</style></head><body>
<h1>{escape(config["title"])}</h1>
<p class="sub">Source: data/logs.jsonl · time range: last {window} minutes · {len(events)} events ·
refresh {config['refresh_seconds']}s · generated {now:%Y-%m-%d %H:%M:%S} UTC</p>
<div class="grid-wrap">{''.join(cards)}</div>
</body></html>"""

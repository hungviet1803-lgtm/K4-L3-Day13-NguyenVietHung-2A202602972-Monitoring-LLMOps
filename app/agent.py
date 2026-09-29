from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from structlog.contextvars import bind_contextvars

from . import metrics
from .mock_llm import FakeLLM
from .mock_rag import retrieve
from .pii import hash_user_id, summarize_text
from .prompt_management import resolve_prompt
from .tracing import (
    current_trace_id,
    get_langfuse_client,
    observe,
    propagate_attributes,
    start_observation,
    tracing_enabled,
)


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    ttft_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float
    trace_id: str | None = None
    prompt_version: str | None = None


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)

    @observe(name="lab-agent-run", as_type="agent", capture_input=False, capture_output=False)
    def run(
        self,
        user_id: str,
        feature: str,
        session_id: str,
        message: str,
        correlation_id: str,
    ) -> AgentResult:
        langfuse_client = get_langfuse_client()
        with propagate_attributes(
            user_id=hash_user_id(user_id),
            session_id=session_id,
            tags=["lab", feature, self.model],
            trace_name="day13-agent-request",
            environment=os.getenv("APP_ENV", "dev"),
            metadata={
                "feature": feature,
                "model": self.model,
                "correlation_id": correlation_id,
            },
        ):
            # Put the trace ID on every later log line so logs link back to Langfuse.
            trace_id = current_trace_id(langfuse_client)
            if trace_id:
                bind_contextvars(trace_id=trace_id)

            started = time.perf_counter()
            with start_observation(
                langfuse_client,
                name="retrieval",
                as_type="retriever",
                input={"query_preview": summarize_text(message)},
            ) as retrieval:
                try:
                    docs = retrieve(message)
                except Exception as exc:
                    retrieval.update(level="ERROR", status_message=type(exc).__name__)
                    raise
                retrieval.update(
                    output={"doc_count": len(docs), "docs_preview": [summarize_text(d) for d in docs]},
                )
            # A cold prompt fetch from Langfuse can take seconds; give it its own span.
            with start_observation(langfuse_client, name="prompt-fetch", as_type="span") as fetch:
                prompt = resolve_prompt(
                    langfuse_client,
                    feature=feature,
                    docs=docs,
                    message=message,
                    enabled=tracing_enabled(),
                )
                fetch.update(
                    output={"prompt_version": prompt.version, "prompt_source": prompt.source},
                    level="WARNING" if prompt.source == "local-fallback" else None,
                )
            langfuse_client.update_current_span(
                metadata={
                    "doc_count": len(docs),
                    "query_preview": summarize_text(message),
                    "prompt_name": prompt.name,
                    "prompt_label": prompt.label,
                    "prompt_version": prompt.version,
                    "prompt_source": prompt.source,
                    "prompt_fetch_error": prompt.fetch_error or "",
                },
                version=prompt.version,
            )
            with propagate_attributes(prompt=prompt.managed_prompt), start_observation(
                langfuse_client,
                name="llm-generation",
                as_type="generation",
                model=self.model,
                prompt=prompt.managed_prompt,
                # Scrubbed preview only: the compiled prompt embeds the raw user message.
                input={"prompt_preview": summarize_text(prompt.text, max_len=200)},
                metadata={"prompt_version": prompt.version, "prompt_label": prompt.label},
            ) as generation:
                generation_started = datetime.now(timezone.utc)
                response = self.llm.generate(prompt.text)
                cost_in, cost_out = self._cost_breakdown(
                    response.usage.input_tokens, response.usage.output_tokens
                )
                generation.update(
                    output={"answer_preview": summarize_text(response.text)},
                    completion_start_time=generation_started + timedelta(milliseconds=response.ttft_ms),
                    usage_details={
                        "input": response.usage.input_tokens,
                        "output": response.usage.output_tokens,
                    },
                    cost_details={"input": cost_in, "output": cost_out},
                )
            quality_score = self._heuristic_quality(message, response.text, docs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            cost_usd = round(cost_in + cost_out, 6)

        metrics.record_request(
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            cost_usd=cost_usd,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
            trace_id=trace_id,
            prompt_version=prompt.version,
        )

    def _cost_breakdown(self, tokens_in: int, tokens_out: int) -> tuple[float, float]:
        input_cost = (tokens_in / 1_000_000) * 3
        output_cost = (tokens_out / 1_000_000) * 15
        return round(input_cost, 6), round(output_cost, 6)

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return round(sum(self._cost_breakdown(tokens_in, tokens_out)), 6)

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)

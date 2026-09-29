from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

try:
    from langfuse import get_client, observe, propagate_attributes

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyClient:
        def update_current_span(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


def get_langfuse_client():
    return get_client()


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )


class _NoopObservation:
    def update(self, **kwargs: Any) -> "_NoopObservation":
        return self


@contextmanager
def start_observation(client: Any, **kwargs: Any):
    """Open a child observation, or a no-op when the client cannot create one."""
    factory = getattr(client, "start_as_current_observation", None)
    if factory is None:
        yield _NoopObservation()
        return
    with factory(**kwargs) as observation:
        yield observation


def current_trace_id(client: Any) -> str | None:
    getter = getattr(client, "get_current_trace_id", None)
    return getter() if getter else None

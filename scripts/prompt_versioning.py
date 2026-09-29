"""Prompt versioning workflow for docs/PROMPT_VERSIONING.md.

    python scripts/prompt_versioning.py setup              # v1 (baseline, production) + v2 (candidate)
    python scripts/prompt_versioning.py run --label candidate
    python scripts/prompt_versioning.py promote --version 2   # move `production` to v2
    python scripts/prompt_versioning.py promote --version 1   # rollback
    python scripts/prompt_versioning.py status
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")

from app.cli import configure_utf8_stdio  # noqa: E402

PROMPT_NAME = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
V1_TEMPLATE = "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}"
V2_TEMPLATE = (
    "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}\n"
    "Answer in at most 3 short sentences."
)
# Same input for every label so traces differ only by prompt version.
SAMPLE_REQUEST = {
    "user_id": "prompt-demo",
    "session_id": "prompt-versioning",
    "feature": "qa",
    "message": "Explain why metrics traces and logs work together",
}


def _client():
    from langfuse import get_client

    return get_client()



def status() -> None:
    client = _client()
    for version in (1, 2, 3, 4, 5):
        try:
            p = client.get_prompt(PROMPT_NAME, version=version, cache_ttl_seconds=0, max_retries=0)
        except Exception:
            break
        print(f"{PROMPT_NAME} v{p.version} labels={p.labels}")


def setup() -> None:
    client = _client()
    try:
        client.get_prompt(PROMPT_NAME, version=1, cache_ttl_seconds=0, max_retries=0)
        print(f"{PROMPT_NAME} already exists, skipping create.")
    except Exception:
        client.create_prompt(
            name=PROMPT_NAME, prompt=V1_TEMPLATE, labels=["baseline", "production"], type="text",
            commit_message="v1 baseline template",
        )
        client.create_prompt(
            name=PROMPT_NAME, prompt=V2_TEMPLATE, labels=["candidate"], type="text",
            commit_message="v2 limit answer length",
        )
    status()


def promote(version: int) -> None:
    client = _client()
    client.update_prompt(name=PROMPT_NAME, version=version, new_labels=["production"])
    print(f"`production` -> v{version}")
    status()


def run(label: str) -> None:
    os.environ["LANGFUSE_PROMPT_LABEL"] = label
    from app.main import app

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
            return await client.post("/chat", json=SAMPLE_REQUEST)

    body = asyncio.run(send()).json()
    client = _client()
    client.flush()
    print(f"label={label} prompt_version={body['prompt_version']}")
    print(f"correlation_id={body['correlation_id']} trace_id={body['trace_id']}")
    print(f"trace_url={client.get_trace_url(trace_id=body['trace_id'])}")


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("status")
    run_p = sub.add_parser("run")
    run_p.add_argument("--label", default="production")
    promote_p = sub.add_parser("promote")
    promote_p.add_argument("--version", type=int, required=True)
    args = parser.parse_args()
    if args.cmd == "setup":
        setup()
    elif args.cmd == "status":
        status()
    elif args.cmd == "run":
        run(args.label)
    else:
        promote(args.version)


if __name__ == "__main__":
    main()

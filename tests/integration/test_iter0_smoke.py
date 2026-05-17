"""Iter 0 smoke test: real call to DashScope OpenAI-compatible endpoint.

Skipped unless DASHSCOPE_API_KEY is available (via env or .env). Enable with
`pytest -m integration`.
"""

import os

import pytest
from dotenv import find_dotenv, load_dotenv

# Load .env early so skipif below sees the key.
load_dotenv(find_dotenv(usecwd=True))

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.environ.get("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY not set in environment or .env",
)
def test_minimal_chat_via_qwen():
    from my_agent.config import load_config
    from my_agent.llm.client import LLMClient
    from my_agent.llm.types import Message

    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    resp = client.send(
        messages=[Message(role="user", content="只回复 OK 两个字符,不要别的")],
        tools=[],
        max_tokens=10,
    )
    assert resp.content
    assert resp.finish_reason in ("stop", "length")

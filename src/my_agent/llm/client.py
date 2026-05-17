import json
import os
import sys

import openai

from .types import Message, Response, ToolCall

DEBUG_ENV_VAR = "MY_AGENT_DEBUG"


def _debug_enabled() -> bool:
    return os.environ.get(DEBUG_ENV_VAR, "").lower() not in ("", "0", "false", "no")


def _debug_dump(label: str, payload: dict) -> None:
    print(f"───── {label} ─────", file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)


class LLMClient:
    """Thin wrapper around openai SDK that speaks our internal Message types.

    Works with any OpenAI-compatible endpoint (Qwen via DashScope, DeepSeek,
    GLM, Kimi, GPT, ...). Switching providers = changing base_url + model + key.

    Set MY_AGENT_DEBUG=1 to dump full request/response JSON to stderr.
    """

    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def send(
        self,
        messages: list[Message],
        tools: list[dict],
        max_tokens: int,
    ) -> Response:
        kwargs: dict = {
            "model": self.model,
            "messages": [m.to_api_dict() for m in messages],
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        if _debug_enabled():
            _debug_dump("REQUEST", kwargs)

        completion = self.client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        msg = choice.message

        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for tc in (msg.tool_calls or [])
        ]

        raw: dict = {}
        if hasattr(completion, "model_dump"):
            try:
                raw = completion.model_dump()
            except Exception:
                pass

        if _debug_enabled():
            _debug_dump("RESPONSE", raw or {"_note": "raw unavailable"})

        return Response(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            raw=raw,
        )

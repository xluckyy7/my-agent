import json
import logging
import os
from typing import Iterator, Optional

import openai

from .types import (
    FinishEvent,
    Message,
    Response,
    TextDelta,
    ToolCall,
    ToolCallDelta,
)

logger = logging.getLogger(__name__)

StreamEvent = TextDelta | ToolCallDelta | FinishEvent

DEBUG_ENV_VAR = "MY_AGENT_DEBUG"


def _debug_enabled() -> bool:
    return os.environ.get(DEBUG_ENV_VAR, "").lower() not in ("", "0", "false", "no")


def _debug_dump(label: str, payload: dict) -> None:
    logger.debug("───── %s ─────\n%s", label, json.dumps(payload, ensure_ascii=False, indent=2))


class LLMClient:
    """Thin wrapper around openai SDK that speaks our internal Message types.

    Works with any OpenAI-compatible endpoint (Qwen via DashScope, DeepSeek,
    GLM, Kimi, GPT, ...). Switching providers = changing base_url + model + key.

    Set MY_AGENT_DEBUG=1 to dump full request/response JSON to stderr.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        hooks: Optional["HookManager"] = None,  # noqa: F821
    ):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self._hooks = hooks

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

        if self._hooks is not None:
            self._hooks.fire(
                "PreModelCall",
                data={"model": self.model, "messages": kwargs["messages"], "stream": False},
                subject=self.model,
            )

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

        response = Response(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            raw=raw,
        )

        if self._hooks is not None:
            self._hooks.fire(
                "PostModelCall",
                data={
                    "model": self.model,
                    "content": response.content,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ],
                    "finish_reason": response.finish_reason,
                    "usage": (raw or {}).get("usage"),
                    "stream": False,
                },
                subject=self.model,
            )
        return response

    def stream(
        self,
        messages: list[Message],
        tools: list[dict],
        max_tokens: int,
    ) -> Iterator[StreamEvent]:
        """Yield StreamEvents incrementally from a streaming chat completion.

        The caller is responsible for accumulating events back into a Response
        (see assemble_stream() for a reference implementation).
        """
        kwargs: dict = {
            "model": self.model,
            "messages": [m.to_api_dict() for m in messages],
            "max_tokens": max_tokens,
            "stream": True,
            # OpenAI-compat streaming protocol: server only emits a final
            # usage chunk (choices=[], usage={...}) when this flag is set.
            # Without it, we'd have no token counts in stream mode at all.
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        if _debug_enabled():
            _debug_dump("REQUEST(stream)", {k: v for k, v in kwargs.items() if k != "stream"})

        if self._hooks is not None:
            self._hooks.fire(
                "PreModelCall",
                data={"model": self.model, "messages": kwargs["messages"], "stream": True},
                subject=self.model,
            )

        chunks = self.client.chat.completions.create(**kwargs)

        debug = _debug_enabled()
        chunk_idx = 0

        # Accumulate state across chunks so PostModelCall (fired once at the
        # end) has the full picture — including the usage chunk that arrives
        # AFTER the finish-reason chunk.
        accumulated_text: list[str] = []
        finish_reason: Optional[str] = None
        usage: Optional[dict] = None

        try:
            for chunk in chunks:
                if debug:
                    raw: dict
                    try:
                        dumped = chunk.model_dump()
                        raw = dumped if isinstance(dumped, dict) else {"_repr": repr(dumped)}
                    except Exception:
                        raw = {"_repr": repr(chunk)}
                    _debug_dump(f"CHUNK[{chunk_idx}]", raw)
                    chunk_idx += 1

                # Usage-only chunks (choices=[]) carry token counts when
                # include_usage is on. They typically arrive AFTER the
                # finish-reason chunk, so we capture but don't skip the loop.
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    try:
                        usage = chunk_usage.model_dump()
                    except Exception:
                        usage = dict(chunk_usage) if chunk_usage else None

                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                content = getattr(delta, "content", None)
                if content:
                    accumulated_text.append(content)
                    yield TextDelta(text=content)

                tool_calls = getattr(delta, "tool_calls", None) or []
                for tc in tool_calls:
                    # Qwen quirk: subsequent chunks for the same tool_call send
                    # id="" and name=None instead of (id=None, name=None). We
                    # normalize empty strings to None at this boundary so the
                    # accumulator's "first-non-null wins" semantics actually work.
                    raw_id = getattr(tc, "id", None)
                    raw_name = getattr(tc.function, "name", None) if tc.function else None
                    yield ToolCallDelta(
                        index=tc.index,
                        id=raw_id or None,
                        name=raw_name or None,
                        arguments_delta=(
                            getattr(tc.function, "arguments", "") or "" if tc.function else ""
                        ),
                    )

                if choice.finish_reason is not None:
                    finish_reason = choice.finish_reason
                    yield FinishEvent(finish_reason=choice.finish_reason)
        finally:
            # Fire Post hook AFTER the whole stream is drained so the usage
            # chunk (which arrives last) is included. finally also covers
            # the case where the consumer abandoned the generator early.
            if self._hooks is not None:
                self._hooks.fire(
                    "PostModelCall",
                    data={
                        "model": self.model,
                        "content": "".join(accumulated_text) or None,
                        "finish_reason": finish_reason,
                        "usage": usage,
                        "stream": True,
                    },
                    subject=self.model,
                )

"""Stream event utilities — assemble events back into a Response."""

from typing import Iterable

from .types import (
    FinishEvent,
    Response,
    TextDelta,
    ToolCall,
    ToolCallDelta,
)


def assemble_stream(events: Iterable) -> Response:
    """Consume a stream of events and return the equivalent Response.

    Mirror of LLMClient.send()'s return shape so callers can substitute
    streaming for non-streaming without changing downstream code.

    Raises ValueError if the stream ends without a FinishEvent — this signals
    a protocol bug, not a recoverable runtime condition.
    """
    text_parts: list[str] = []
    # index → {"id": str, "name": str, "args": str}
    tc_acc: dict[int, dict] = {}
    finish_reason: str | None = None
    saw_text_delta = False

    for ev in events:
        if isinstance(ev, TextDelta):
            text_parts.append(ev.text)
            saw_text_delta = True
        elif isinstance(ev, ToolCallDelta):
            slot = tc_acc.setdefault(
                ev.index, {"id": None, "name": None, "args": ""}
            )
            if ev.id is not None:
                slot["id"] = ev.id
            if ev.name is not None:
                slot["name"] = ev.name
            slot["args"] += ev.arguments_delta
        elif isinstance(ev, FinishEvent):
            finish_reason = ev.finish_reason
            # FinishEvent is terminal; anything after is ignored.
            break

    if finish_reason is None:
        raise ValueError("stream ended without a FinishEvent")

    tool_calls: list[ToolCall] = [
        ToolCall(
            id=tc_acc[i]["id"] or "",
            name=tc_acc[i]["name"] or "",
            arguments=tc_acc[i]["args"],
        )
        for i in sorted(tc_acc.keys())
    ]

    content = "".join(text_parts) if saw_text_delta else None

    return Response(
        content=content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
    )

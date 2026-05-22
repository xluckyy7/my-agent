"""Langfuse observability plugin for my-agent.

Wires the hook system into Langfuse (https://langfuse.com) so every model
call and tool call shows up as a structured observation in their dashboard.

Setup:
  1. Sign up at https://cloud.langfuse.com (or self-host)
  2. Export keys:
        export LANGFUSE_PUBLIC_KEY=pk-...
        export LANGFUSE_SECRET_KEY=sk-...
        export LANGFUSE_HOST=https://cloud.langfuse.com  # or self-hosted URL
  3. Add to ~/.my-agent/hooks.json:
        {
          "hooks": {
            "UserPromptSubmit": [{"type": "python",
              "module": "my_agent.plugins.langfuse_plugin",
              "function": "on_user_prompt_submit"}],
            "PreModelCall":     [{"type": "python", "module": "my_agent.plugins.langfuse_plugin",
              "function": "on_pre_model_call"}],
            "PostModelCall":    [{"type": "python", "module": "my_agent.plugins.langfuse_plugin",
              "function": "on_post_model_call"}],
            "PreToolUse":       [{"type": "python", "module": "my_agent.plugins.langfuse_plugin",
              "function": "on_pre_tool_use"}],
            "PostToolUse":      [{"type": "python", "module": "my_agent.plugins.langfuse_plugin",
              "function": "on_post_tool_use"}],
            "Stop":             [{"type": "python", "module": "my_agent.plugins.langfuse_plugin",
              "function": "on_stop"}]
          }
        }

State model: module-level dicts keep per-session span stacks. This is OK
because hooks fire synchronously from the agent loop on the same thread; no
locking needed for single-CLI use. For the web server with concurrent
sessions, langfuse's OTel-based context still scopes per call, but to be
safe each session gets its own bag of spans keyed by session_id.
"""

import logging
import os
from threading import Lock
from typing import Any, Optional

logger = logging.getLogger(__name__)

_client: Any = None
_client_lock = Lock()
_sessions: dict[str, dict] = {}  # session_id → {"span_stack": [...]}


def _ensure_client():
    """Lazy-construct the Langfuse client (idempotent, thread-safe).

    Returns None if keys aren't configured — hooks degrade to no-op,
    plugin won't crash the agent.

    Host resolution: accepts either LANGFUSE_HOST (the SDK's canonical name)
    or LANGFUSE_BASE_URL (common alternate spelling). When neither is set,
    the SDK falls back to its built-in default (cloud.langfuse.com). Useful
    for self-hosted deployments where users may have either name in .env.
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get(
            "LANGFUSE_SECRET_KEY"
        ):
            logger.warning(
                "missing LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY; plugin disabled"
            )
            return None
        host = os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL")
        try:
            from langfuse import Langfuse

            kwargs: dict = {}
            if host:
                kwargs["host"] = host
            _client = Langfuse(**kwargs)
            logger.info(
                "initialized (host=%s)", host or "default cloud.langfuse.com"
            )
        except Exception as e:
            logger.error("init failed: %s", e)
            _client = None
        return _client


def _session_id(event) -> str:
    return event.data.get("session_id") or "default"


def _state(event) -> dict:
    sid = _session_id(event)
    if sid not in _sessions:
        _sessions[sid] = {"span_stack": []}
    return _sessions[sid]


def _push(event, span) -> None:
    _state(event)["span_stack"].append(span)


def _pop(event):
    stack = _state(event)["span_stack"]
    return stack.pop() if stack else None


def _peek(event):
    stack = _state(event)["span_stack"]
    return stack[-1] if stack else None


# ===================================================================
# Helpers: format normalization for langfuse 4.x
# ===================================================================


def _map_openai_usage(usage: Optional[dict]) -> Optional[dict]:
    """Convert OpenAI/Qwen-shaped usage to Langfuse-shaped usage.

    OpenAI:   {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
    Langfuse: {"input": N, "output": N, "total": N}

    Langfuse will display 0 token counts on the dashboard if we hand it the
    OpenAI shape unchanged, because it reads `input/output/total`, not
    `prompt_tokens/completion_tokens/total_tokens`.
    """
    if not usage:
        return None
    out: dict = {}
    if (v := usage.get("prompt_tokens")) is not None:
        out["input"] = v
    if (v := usage.get("completion_tokens")) is not None:
        out["output"] = v
    if (v := usage.get("total_tokens")) is not None:
        out["total"] = v
    return out or None


def _tag_session_on_root(span, session_id: str) -> None:
    """Attach session.id to the root span as an OTel attribute.

    Langfuse's Sessions view aggregates by the `session.id` OTel attribute on
    the root span, NOT by metadata. We set it on the underlying OTel span
    (accessed via the SDK's `_otel_span` extension point) using the SDK's
    own constant for the attribute name.

    Failure here is non-fatal — session tagging is nice-to-have, not critical.
    """
    if not session_id:
        return
    try:
        from langfuse import LangfuseOtelSpanAttributes

        span._otel_span.set_attribute(
            LangfuseOtelSpanAttributes.TRACE_SESSION_ID, session_id
        )
    except Exception as e:
        logger.debug("could not tag session.id on root span: %s", e)


# ===================================================================
# Hook entry points (referenced from ~/.my-agent/hooks.json)
# ===================================================================


def on_user_prompt_submit(event) -> None:
    """Open the turn (root) span. session.id is set as an OTel attribute on
    THIS span so the Langfuse Sessions view aggregates correctly.

    Also sets trace-level input via set_trace_io — without this, the Traces
    list's Input column is empty for any multi-span trace (langfuse only
    auto-promotes root span input when the trace has exactly one span).
    """
    client = _ensure_client()
    if client is None:
        return
    sid = _session_id(event)
    prompt = event.data.get("prompt", "")
    span = client.start_observation(
        name="turn",
        as_type="span",
        input={"prompt": prompt},
        metadata={"stream": event.data.get("stream", False)},
    )
    _tag_session_on_root(span, sid)
    try:
        span.set_trace_io(input={"prompt": prompt})
    except Exception as e:
        logger.debug("could not set trace input: %s", e)
    _push(event, span)


def on_pre_model_call(event) -> None:
    """Open an llm_call generation as a CHILD of the current turn span.

    Using `parent.start_observation(...)` rather than `client.start_observation`
    is what gives us the parent→child relationship in the trace tree (langfuse
    4.x is OTel-based; client-level calls produce detached root spans).
    """
    if _ensure_client() is None:
        return
    parent = _peek(event)
    if parent is None:
        logger.debug("PreModelCall fired without active turn span; skipping")
        return
    gen = parent.start_observation(
        name="llm_call",
        as_type="generation",
        model=event.data.get("model"),
        input=event.data.get("messages"),
        metadata={"stream": event.data.get("stream", False)},
    )
    _push(event, gen)


def on_post_model_call(event) -> None:
    if _ensure_client() is None:
        return
    gen = _pop(event)
    if gen is None:
        return
    try:
        gen.update(
            output={
                "content": event.data.get("content"),
                "tool_calls": event.data.get("tool_calls"),
                "finish_reason": event.data.get("finish_reason"),
            },
            usage_details=_map_openai_usage(event.data.get("usage")),
        )
        gen.end()
    except Exception as e:
        logger.warning("post-model update failed: %s", e)


def on_pre_tool_use(event) -> None:
    """Open a tool span as a CHILD of the current turn span. Uses
    `as_type='tool'` so the Langfuse UI renders it as a proper tool node."""
    if _ensure_client() is None:
        return
    parent = _peek(event)
    if parent is None:
        logger.debug("PreToolUse fired without active turn span; skipping")
        return
    span = parent.start_observation(
        name=event.data.get("tool_name", "?"),
        as_type="tool",
        input={"arguments": event.data.get("arguments", "")},
    )
    _push(event, span)


def on_post_tool_use(event) -> None:
    if _ensure_client() is None:
        return
    span = _pop(event)
    if span is None:
        return
    try:
        span.update(
            output=event.data.get("content"),
            level="ERROR" if event.data.get("is_error") else "DEFAULT",
        )
        span.end()
    except Exception as e:
        logger.warning("post-tool update failed: %s", e)


def on_stop(event) -> None:
    client = _ensure_client()
    if client is None:
        return
    # Close the "turn" span pushed at UserPromptSubmit
    turn_span = _pop(event)
    if turn_span is not None:
        final_text = event.data.get("final_text", "")
        try:
            turn_span.update(output={"final_text": final_text})
        except Exception as e:
            logger.warning("stop update failed: %s", e)
        # set_trace_io is independent of update() — sets the trace-level
        # output that shows in the Traces list Output column.
        try:
            turn_span.set_trace_io(output={"final_text": final_text})
        except Exception as e:
            logger.debug("could not set trace output: %s", e)
        try:
            turn_span.end()
        except Exception as e:
            logger.warning("stop end failed: %s", e)
    try:
        client.flush()
    except Exception as e:
        logger.warning("flush failed: %s", e)


# ===================================================================
# Test seam — reset module-level state for tests
# ===================================================================


def _reset_for_tests() -> None:
    global _client
    _client = None
    _sessions.clear()

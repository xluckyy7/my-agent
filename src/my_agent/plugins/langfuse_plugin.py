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

import os
import sys
from threading import Lock
from typing import Any

_client: Any = None
_client_lock = Lock()
_sessions: dict[str, dict] = {}  # session_id → {"span_stack": [...]}


def _ensure_client():
    """Lazy-construct the Langfuse client (idempotent, thread-safe).

    Returns None if keys aren't configured — hooks degrade to no-op,
    plugin won't crash the agent.
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
            print(
                "[langfuse] missing LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY; "
                "plugin disabled",
                file=sys.stderr,
            )
            return None
        try:
            from langfuse import Langfuse

            _client = Langfuse()
        except Exception as e:
            print(f"[langfuse] init failed: {e}", file=sys.stderr)
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
# Hook entry points (referenced from ~/.my-agent/hooks.json)
# ===================================================================


def on_user_prompt_submit(event) -> None:
    client = _ensure_client()
    if client is None:
        return
    sid = _session_id(event)
    span = client.start_observation(
        name="turn",
        as_type="span",
        input={"prompt": event.data.get("prompt", "")},
        metadata={"session_id": sid, "stream": event.data.get("stream", False)},
    )
    _push(event, span)


def on_pre_model_call(event) -> None:
    client = _ensure_client()
    if client is None:
        return
    gen = client.start_observation(
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
            usage_details=event.data.get("usage") or None,
        )
        gen.end()
    except Exception as e:
        print(f"[langfuse] post-model update failed: {e}", file=sys.stderr)


def on_pre_tool_use(event) -> None:
    client = _ensure_client()
    if client is None:
        return
    span = client.start_observation(
        name=f"tool:{event.data.get('tool_name', '?')}",
        as_type="span",
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
        print(f"[langfuse] post-tool update failed: {e}", file=sys.stderr)


def on_stop(event) -> None:
    client = _ensure_client()
    if client is None:
        return
    # Close the "turn" span pushed at UserPromptSubmit
    turn_span = _pop(event)
    if turn_span is not None:
        try:
            turn_span.update(output={"final_text": event.data.get("final_text", "")})
            turn_span.end()
        except Exception as e:
            print(f"[langfuse] stop update failed: {e}", file=sys.stderr)
    try:
        client.flush()
    except Exception as e:
        print(f"[langfuse] flush failed: {e}", file=sys.stderr)


# ===================================================================
# Test seam — reset module-level state for tests
# ===================================================================


def _reset_for_tests() -> None:
    global _client
    _client = None
    _sessions.clear()

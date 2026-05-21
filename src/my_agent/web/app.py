"""FastAPI app exposing my-agent as an HTTP service with SSE streaming.

Use `build_app(loop_factory, system_prompt)` so tests can inject a fake
AgentLoop without spawning real LLMs.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from my_agent.agent.events import TurnTextDelta, TurnToolEnd, TurnToolStart

from .sessions import SessionStore


class ChatRequest(BaseModel):
    prompt: str
    session_id: str = "default"


def _event_to_dict(ev) -> dict:
    """Serialize a TurnEvent to a dict suitable for SSE JSON."""
    if isinstance(ev, TurnTextDelta):
        return {"type": "text_delta", "text": ev.text}
    if isinstance(ev, TurnToolStart):
        return {
            "type": "tool_start",
            "tool_call_id": ev.tool_call_id,
            "name": ev.name,
            "arguments": ev.arguments,
        }
    if isinstance(ev, TurnToolEnd):
        return {
            "type": "tool_end",
            "tool_call_id": ev.tool_call_id,
            "name": ev.name,
            "content": ev.content,
            "is_error": ev.is_error,
            "duration_seconds": ev.duration_seconds,
        }
    # Unknown event — best effort
    try:
        return {"type": type(ev).__name__, **asdict(ev)}
    except Exception:
        return {"type": type(ev).__name__, "repr": repr(ev)}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


_INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>my-agent</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 720px; margin: 24px auto; padding: 0 16px; }
  #log { white-space: pre-wrap; border: 1px solid #ccc; padding: 12px; min-height: 300px; border-radius: 6px; background: #fafafa; }
  .tool { color: #0a7; font-size: 0.9em; }
  .tool-end { color: #690; font-size: 0.9em; }
  .err { color: #c33; }
  form { display: flex; gap: 8px; margin-top: 12px; }
  input { flex: 1; padding: 8px; }
  button { padding: 8px 16px; }
</style>
</head><body>
<h1>my-agent v1.0</h1>
<div id="log"></div>
<form id="f">
  <input id="q" autocomplete="off" placeholder="问点什么..." autofocus />
  <button>Send</button>
</form>
<script>
const log = document.getElementById('log');
const form = document.getElementById('f');
const q = document.getElementById('q');
const sessionId = 'web-' + Math.random().toString(36).slice(2, 10);

function append(text, cls) {
  const span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text;
  log.appendChild(span);
  log.scrollTop = log.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const prompt = q.value.trim();
  if (!prompt) return;
  q.value = '';
  append('\\n\\n>>> ' + prompt + '\\n');

  const resp = await fetch('/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({prompt, session_id: sessionId}),
  });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buf += decoder.decode(value, {stream: true});
    let idx;
    while ((idx = buf.indexOf('\\n\\n')) >= 0) {
      const line = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (!line.startsWith('data: ')) continue;
      const ev = JSON.parse(line.slice(6));
      if (ev.type === 'text_delta')      append(ev.text);
      else if (ev.type === 'tool_start') append('\\n  ▸ ' + ev.name + ' ' + (ev.arguments || '').slice(0, 80) + '\\n', 'tool');
      else if (ev.type === 'tool_end')   append('    ' + (ev.is_error ? '✗' : '✓') + ' ' + ev.duration_seconds.toFixed(2) + 's\\n', 'tool-end');
      else if (ev.type === 'error')      append('\\n[error] ' + ev.message + '\\n', 'err');
      else if (ev.type === 'done')       break;
    }
  }
});
</script></body></html>
"""


def build_app(loop_factory: Callable, system_prompt: str) -> FastAPI:
    """Construct the FastAPI app with given AgentLoop factory + system prompt."""
    app = FastAPI(title="my-agent", version="1.0.0")
    sessions = SessionStore(system_prompt=system_prompt)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _INDEX_HTML

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/sessions")
    async def list_sessions():
        return {"sessions": sessions.ids(), "count": len(sessions)}

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        existed = sessions.reset(session_id)
        if not existed:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True}

    @app.post("/chat")
    async def chat(req: ChatRequest):
        conv = sessions.get_or_create(req.session_id)
        loop = loop_factory()

        def gen():
            try:
                for ev in loop.run_turn_stream(conv, req.prompt):
                    yield _sse(_event_to_dict(ev))
                yield _sse({"type": "done"})
            except Exception as e:
                yield _sse({"type": "error", "message": str(e)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app

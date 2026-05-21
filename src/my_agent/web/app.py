"""FastAPI app exposing my-agent as an HTTP service with SSE streaming.

Use `build_app(loop_factory, system_prompt)` so tests can inject a fake
AgentLoop without spawning real LLMs.
"""

import json
import uuid
from dataclasses import asdict
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


_INDEX_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>my-agent</title>
<style>
  :root {
    --sidebar-w: 280px;
    --bg: #ffffff;
    --bg-alt: #f7f7f8;
    --bg-hover: #ececec;
    --bg-active: #e0e0e0;
    --border: #e5e5e5;
    --text: #202020;
    --text-mute: #8a8a8a;
    --accent: #1a6cff;
    --tool-fg: #0a7;
    --tool-end-fg: #690;
    --err-fg: #c33;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--text); }
  body { display: flex; }

  /* ---------- sidebar ---------- */
  .sidebar {
    width: var(--sidebar-w);
    background: var(--bg-alt);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }
  .sidebar-header {
    padding: 12px;
    border-bottom: 1px solid var(--border);
  }
  .new-chat-btn {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    text-align: left;
  }
  .new-chat-btn:hover { background: var(--bg-hover); }

  .sessions-list { flex: 1; overflow-y: auto; padding: 8px; }
  .session-item {
    padding: 8px 12px;
    border-radius: 6px;
    cursor: pointer;
    margin-bottom: 2px;
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  .session-item:hover { background: var(--bg-hover); }
  .session-item.active { background: var(--bg-active); }
  .session-body { flex: 1; min-width: 0; }
  .session-title {
    font-size: 13px;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .session-meta {
    color: var(--text-mute);
    font-size: 11px;
    margin-top: 2px;
  }
  .session-delete {
    opacity: 0;
    background: none;
    border: none;
    color: var(--text-mute);
    cursor: pointer;
    padding: 2px 4px;
    font-size: 14px;
    line-height: 1;
  }
  .session-item:hover .session-delete { opacity: 1; }
  .session-delete:hover { color: var(--err-fg); }
  .empty-state { padding: 16px; color: var(--text-mute); font-size: 13px; text-align: center; }

  /* ---------- main pane ---------- */
  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px 24px;
    max-width: 800px;
    width: 100%;
    margin: 0 auto;
  }
  .msg { margin-bottom: 18px; }
  .msg-role {
    font-size: 11px;
    color: var(--text-mute);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
  }
  .msg-content { white-space: pre-wrap; line-height: 1.55; }
  .msg.user .msg-content { color: var(--accent); }
  .tool-line {
    color: var(--tool-fg);
    font-size: 13px;
    margin: 4px 0;
    font-family: ui-monospace, monospace;
  }
  .tool-end-line {
    color: var(--tool-end-fg);
    font-size: 12px;
    margin: 2px 0 8px 16px;
    font-family: ui-monospace, monospace;
  }
  .err { color: var(--err-fg); }
  .welcome {
    color: var(--text-mute);
    font-size: 14px;
    text-align: center;
    margin-top: 40px;
  }

  .input-area {
    border-top: 1px solid var(--border);
    padding: 12px 24px 16px;
    max-width: 800px;
    width: 100%;
    margin: 0 auto;
  }
  .input-row { display: flex; gap: 8px; }
  #q {
    flex: 1;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 14px;
    font-family: inherit;
  }
  #q:focus { outline: none; border-color: var(--accent); }
  #send {
    padding: 10px 18px;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
  }
  #send:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
</head><body>

<div class="sidebar">
  <div class="sidebar-header">
    <button class="new-chat-btn" id="newChatBtn">+ New chat</button>
  </div>
  <div class="sessions-list" id="sessions"></div>
</div>

<div class="main">
  <div class="messages" id="messages">
    <div class="welcome">Start a new chat or select one from the sidebar.</div>
  </div>
  <div class="input-area">
    <form id="f">
      <div class="input-row">
        <input id="q" autocomplete="off" placeholder="问点什么..." autofocus />
        <button id="sendBtn" type="submit">Send</button>
      </div>
    </form>
  </div>
</div>

<script>
const $sessions = document.getElementById('sessions');
const $messages = document.getElementById('messages');
const $q = document.getElementById('q');
const $sendBtn = document.getElementById('sendBtn');
const $form = document.getElementById('f');
const $newChatBtn = document.getElementById('newChatBtn');

let currentId = localStorage.getItem('my-agent-session') || null;

// ---------- helpers ----------

function fmtTime(epoch) {
  const d = new Date(epoch * 1000);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) {
    return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  }
  return d.toLocaleDateString();
}

function $el(tag, props = {}, children = []) {
  const e = document.createElement(tag);
  Object.entries(props).forEach(([k, v]) => {
    if (k === 'class') e.className = v;
    else if (k === 'onclick') e.onclick = v;
    else if (k === 'text') e.textContent = v;
    else e.setAttribute(k, v);
  });
  children.forEach(c => e.appendChild(c));
  return e;
}

function clearMessages() {
  $messages.innerHTML = '';
}

function appendMessage(role, content) {
  const div = $el('div', {class: 'msg ' + role});
  div.appendChild($el('div', {class: 'msg-role', text: role}));
  const body = $el('div', {class: 'msg-content', text: content || ''});
  div.appendChild(body);
  $messages.appendChild(div);
  $messages.scrollTop = $messages.scrollHeight;
  return body;
}

function appendInline(text, cls) {
  // Append a small line attached to the most recent assistant message
  const lastAssistant = $messages.querySelector('.msg.assistant:last-of-type .msg-content');
  if (!lastAssistant) return appendMessage('assistant', text);
  const span = $el('div', {class: cls});
  span.textContent = text;
  lastAssistant.parentNode.insertBefore(span, lastAssistant.nextSibling);
  $messages.scrollTop = $messages.scrollHeight;
}

// ---------- sessions sidebar ----------

async function loadSessions() {
  const r = await fetch('/sessions');
  const data = await r.json();
  renderSessions(data.sessions);
}

function renderSessions(items) {
  $sessions.innerHTML = '';
  if (!items.length) {
    $sessions.appendChild($el('div', {class: 'empty-state', text: 'No conversations yet.'}));
    return;
  }
  items.forEach(s => {
    const isActive = s.id === currentId;
    const item = $el('div', {class: 'session-item' + (isActive ? ' active' : ''), onclick: () => selectSession(s.id)});
    const body = $el('div', {class: 'session-body'});
    body.appendChild($el('div', {class: 'session-title', text: s.title || '(empty)'}));
    body.appendChild($el('div', {class: 'session-meta', text: `${s.message_count} msgs · ${fmtTime(s.last_used_at)}`}));
    item.appendChild(body);
    const del = $el('button', {class: 'session-delete', text: '×', title: 'Delete', onclick: (e) => { e.stopPropagation(); deleteSession(s.id); }});
    item.appendChild(del);
    $sessions.appendChild(item);
  });
}

async function selectSession(id) {
  currentId = id;
  localStorage.setItem('my-agent-session', id);
  // Load message history
  clearMessages();
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(id)}/messages`);
    if (r.ok) {
      const data = await r.json();
      data.messages.forEach(m => appendMessage(m.role, m.content));
    }
  } catch (e) { /* ignore */ }
  await loadSessions();  // re-render to update active state
  $q.focus();
}

async function newChat() {
  const r = await fetch('/sessions', {method: 'POST'});
  const data = await r.json();
  await loadSessions();
  await selectSession(data.session_id);
}

async function deleteSession(id) {
  if (!confirm('Delete this conversation?')) return;
  await fetch(`/sessions/${encodeURIComponent(id)}`, {method: 'DELETE'});
  if (currentId === id) {
    currentId = null;
    localStorage.removeItem('my-agent-session');
    clearMessages();
    $messages.appendChild($el('div', {class: 'welcome', text: 'Start a new chat or select one from the sidebar.'}));
  }
  await loadSessions();
}

// ---------- chat ----------

async function send() {
  const prompt = $q.value.trim();
  if (!prompt) return;

  $sendBtn.disabled = true;

  try {
    if (!currentId) {
      // Auto-create a fresh session on first send
      const r = await fetch('/sessions', {method: 'POST'});
      const data = await r.json();
      currentId = data.session_id;
      localStorage.setItem('my-agent-session', currentId);
      clearMessages();
    }

    $q.value = '';

    appendMessage('user', prompt);
    const assistantBody = appendMessage('assistant', '');

    const resp = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt, session_id: currentId}),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (!line.startsWith('data: ')) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === 'text_delta') {
          assistantBody.textContent += ev.text;
          $messages.scrollTop = $messages.scrollHeight;
        } else if (ev.type === 'tool_start') {
          appendInline(`  ▸ ${ev.name} ${(ev.arguments || '').slice(0, 80)}`, 'tool-line');
        } else if (ev.type === 'tool_end') {
          const mark = ev.is_error ? '✗' : '✓';
          appendInline(`    ${mark} ${ev.duration_seconds.toFixed(2)}s`, 'tool-end-line');
        } else if (ev.type === 'error') {
          const errDiv = $el('div', {class: 'err', text: '[error] ' + ev.message});
          assistantBody.parentNode.appendChild(errDiv);
        } else if (ev.type === 'done') {
          break;
        }
      }
    }
  } catch (err) {
    console.error('send failed:', err);
    const errDiv = $el('div', {class: 'err', text: '[network error] ' + err.message});
    $messages.appendChild(errDiv);
  } finally {
    $sendBtn.disabled = false;
    $q.focus();
    await loadSessions();  // refresh titles/counts
  }
}

// ---------- init ----------

$form.addEventListener('submit', (e) => { e.preventDefault(); send(); });
$newChatBtn.addEventListener('click', () => { newChat(); });

(async () => {
  await loadSessions();
  if (currentId) await selectSession(currentId);
})();
</script>
</body></html>
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
        return {"sessions": [asdict(s) for s in sessions.all_info()]}

    @app.post("/sessions")
    async def create_session():
        sid = uuid.uuid4().hex[:12]
        sessions.get_or_create(sid)
        return {"session_id": sid}

    @app.get("/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        conv = sessions.get(session_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {
            "messages": [
                {"role": m.role, "content": m.content or ""}
                for m in conv.messages
                if m.role in ("user", "assistant")
            ]
        }

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

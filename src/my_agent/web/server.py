"""Entry point: `python -m my_agent.web` starts a uvicorn server.

Wires up Config + LLMClient + tool registry + ContextManager + memory just
like the CLI, but exposes them via FastAPI/SSE instead of REPL.
"""

import os
from pathlib import Path

import uvicorn

from my_agent._logging import setup_logging
from my_agent.agent.context import ContextManager
from my_agent.agent.loop import AgentLoop
from my_agent.agent.memory import (
    compose_system_prompt,
    load_project_memory,
    load_user_memory,
)
from my_agent.cli.main import DEFAULT_SYSTEM_PROMPT, build_hook_manager, build_registry
from my_agent.config import load_config
from my_agent.llm.client import LLMClient

from .app import build_app


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    setup_logging()
    cfg = load_config()
    home = Path(os.environ.get("HOME", str(Path.home())))
    cwd = Path.cwd()

    hooks = build_hook_manager(home)
    client = LLMClient(
        api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model, hooks=hooks
    )
    registry = build_registry(home=home, client=client, hooks=hooks)
    hooks.fire("SessionStart", data={"mode": "web"})

    # Each request builds a fresh AgentLoop (cheap; just a class wrapper).
    # Session state lives in SessionStore inside the FastAPI app.
    def loop_factory() -> AgentLoop:
        context_mgr = ContextManager(
            client=client,
            budget=cfg.context_budget,
            keep_recent_turns=cfg.keep_recent_turns,
        )
        return AgentLoop(
            client=client,
            tools=registry,
            max_tokens=cfg.max_tokens,
            context_mgr=context_mgr,
            hooks=hooks,
        )

    system_prompt = compose_system_prompt(
        base=DEFAULT_SYSTEM_PROMPT,
        project=load_project_memory(cwd),
        user=load_user_memory(home),
    )
    # Web sessions persist to ~/.my-agent/web-sessions/ so they survive
    # uvicorn restarts. Each session is one JSON file there.
    sessions_dir = home / ".my-agent" / "web-sessions"
    app = build_app(
        loop_factory=loop_factory,
        system_prompt=system_prompt,
        data_dir=sessions_dir,
    )

    print(f"my-agent web ▸ http://{host}:{port}")
    print(f"             sessions ▸ {sessions_dir}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import sys

    host = os.environ.get("MY_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("MY_AGENT_PORT", "8000"))
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    serve(host=host, port=port)

# Project memory for my-agent

You are running inside the `my-agent` repo. This is itself an agent project
(yes, an agent that helps build itself). Apply the following whenever
relevant:

## Project conventions

- Each "iteration" (v0.X) is a feature milestone, tagged `vX.Y`. Commit
  messages for an iteration use `feat(iterN): ...` prefix.
- Tests are organized as:
  - `tests/unit/` — mock-based, run by default, must be < 5s in aggregate
  - `tests/integration/` — real API calls, skipped unless `pytest -m integration`
- Production code lives under `src/my_agent/`. Stick to the existing module
  boundaries: `agent/`, `llm/`, `tools/`, `cli/`.
- Internal message model uses OpenAI native format (role/content/tool_calls/
  tool_call_id). Do NOT introduce a parallel "translated" representation.

## When asked to add a new tool

1. Implement in `src/my_agent/tools/<area>.py` as a `Tool` dataclass with
   detailed `description` (the description is part of the LLM prompt — make
   it informative).
2. Register in `src/my_agent/cli/main.py` `build_registry()`.
3. Write tests covering normal path + error path + schema shape.

## When asked to modify existing behavior

- Check `Conversation.validate()` invariants are still satisfied (see
  `src/my_agent/agent/conversation.py`).
- If touching streaming, remember both `LLMClient.stream` and
  `assemble_stream` must stay in sync.
- Run the full unit suite before declaring "done".

## Safety

- NEVER write API keys, tokens, or `.env` contents into AGENT.md or
  MEMORY.md.
- NEVER overwrite README.md or this file without explicit user request.
- `run_bash` tool has no sandbox — use with care.

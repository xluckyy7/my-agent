"""The `task` tool — spawns a focused sub-agent in an isolated conversation.

Why have it:
  Some sub-tasks need many tool calls to complete (e.g., "find the largest
  Python file under src/" might need ls, find, wc, sort). If those run in
  the parent conversation, parent's history pollutes with intermediate
  tool_calls/results. With a sub-agent, the parent only sees the final
  summary text.

Design:
  - Sub-agent shares the parent's LLMClient and tool list (so it has the
    same capabilities).
  - Sub-agent has its OWN Conversation, seeded with a focused system prompt.
  - Recursion depth is capped (max_depth) — sub-agents at the boundary
    don't get a `task` tool, so they cannot spawn further.
  - Sub-agent runs without ContextManager (it's transient and short-lived).
"""

from my_agent.agent.conversation import Conversation
from my_agent.agent.loop import AgentLoop
from my_agent.llm.client import LLMClient

from .base import Tool, ToolRegistry

SUB_AGENT_SYSTEM_PROMPT = (
    "You are a focused sub-agent. A parent agent has given you a specific, "
    "self-contained subtask in the user message. Use the available tools to "
    "complete it, then return a concise summary (preferably under 500 words) "
    "of what you found and did. Do NOT ask for clarification — just do your "
    "best with the description provided. Your reply is consumed by the parent "
    "agent, not shown to a human, so be terse and information-dense."
)


def make_task_tool(
    *,
    client: LLMClient,
    base_tools: list[Tool],
    depth: int = 0,
    max_depth: int = 2,
    sub_system_prompt: str = SUB_AGENT_SYSTEM_PROMPT,
    sub_max_iterations: int = 20,
    sub_max_tokens: int = 4096,
) -> Tool:
    """Build a `task` Tool. The tool, when invoked, spawns a sub-agent.

    The sub-agent's registry is composed at call time:
      base_tools + (a `task` tool of its own iff depth+1 < max_depth)
    """

    def _spawn(args: dict) -> str:
        description = args["description"]
        next_depth = depth + 1

        sub_registry = ToolRegistry()
        for t in base_tools:
            sub_registry.register(t)
        if next_depth < max_depth:
            sub_registry.register(
                make_task_tool(
                    client=client,
                    base_tools=base_tools,
                    depth=next_depth,
                    max_depth=max_depth,
                    sub_system_prompt=sub_system_prompt,
                    sub_max_iterations=sub_max_iterations,
                    sub_max_tokens=sub_max_tokens,
                )
            )

        sub_loop = AgentLoop(
            client=client,
            tools=sub_registry,
            max_iterations=sub_max_iterations,
            max_tokens=sub_max_tokens,
            context_mgr=None,  # sub-agent is transient; no compaction
        )
        sub_conv = Conversation(system=sub_system_prompt)
        return sub_loop.run_turn(sub_conv, description)

    return Tool(
        name="task",
        description=(
            "Spawn a focused sub-agent to handle a self-contained subtask. The "
            "sub-agent has access to all the same tools you do, but runs in "
            "its own conversation — its intermediate tool calls do NOT "
            "pollute yours. Returns a concise summary of what the sub-agent "
            "found or did. Use this for: (a) tasks needing many tool calls "
            "where you only care about the final result; (b) parallelizable "
            "work (call task multiple times in one turn); (c) keeping the "
            "main conversation context clean."
        ),
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": (
                        "Self-contained subtask description. Be specific — "
                        "the sub-agent CANNOT ask for clarification. Include "
                        "any necessary file paths, URLs, or constraints."
                    ),
                },
            },
            "required": ["description"],
        },
        fn=_spawn,
    )

import sys

from my_agent.config import load_config
from my_agent.llm.client import LLMClient
from my_agent.llm.types import Message
from my_agent.tools.base import ToolRegistry
from my_agent.tools.files import read_file_tool

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. You can call tools to read files when needed."
)


def build_registry() -> ToolRegistry:
    """Wire up the v0.1 tool set."""
    reg = ToolRegistry()
    reg.register(read_file_tool)
    return reg


def run_once(client: LLMClient, prompt: str, system: str = DEFAULT_SYSTEM_PROMPT) -> str:
    """Iter 1 contract: at most ONE tool round.

    Flow:
      1. send(system + user) → either stop, or tool_calls
      2. if tool_calls: dispatch all of them, append tool messages
      3. send again → expect stop, return final text
    """
    registry = build_registry()
    schemas = registry.get_schemas()

    messages: list[Message] = [
        Message(role="system", content=system),
        Message(role="user", content=prompt),
    ]

    resp = client.send(messages, tools=schemas, max_tokens=4096)
    messages.append(
        Message(
            role="assistant",
            content=resp.content,
            tool_calls=resp.tool_calls or None,
        )
    )

    if resp.finish_reason != "tool_calls":
        return resp.content or ""

    for tc in resp.tool_calls:
        result = registry.dispatch(tc.name, tc.arguments)
        messages.append(
            Message(
                role="tool",
                tool_call_id=tc.id,
                name=tc.name,
                content=result.content,
            )
        )

    final = client.send(messages, tools=schemas, max_tokens=4096)
    return final.content or ""


def app() -> int:
    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)

    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        prompt = input(">>> ").strip()
    if not prompt:
        return 0

    print(run_once(client, prompt))
    return 0


if __name__ == "__main__":
    sys.exit(app())

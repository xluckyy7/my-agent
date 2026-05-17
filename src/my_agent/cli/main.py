import sys

from my_agent.config import load_config
from my_agent.llm.client import LLMClient
from my_agent.llm.types import Message


def app() -> int:
    """One-shot chat: read prompt from argv (or stdin) and print the model's reply.

    Iter 0 contract: no tools, no history, no streaming.
    """
    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)

    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        prompt = input(">>> ").strip()
    if not prompt:
        return 0

    messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content=prompt),
    ]
    resp = client.send(messages, tools=[], max_tokens=cfg.max_tokens)
    print(resp.content or "")
    return 0


if __name__ == "__main__":
    sys.exit(app())

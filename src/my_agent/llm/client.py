import openai

from .types import Message, Response, ToolCall


class LLMClient:
    """Thin wrapper around openai SDK that speaks our internal Message types.

    Works with any OpenAI-compatible endpoint (Qwen via DashScope, DeepSeek,
    GLM, Kimi, GPT, ...). Switching providers = changing base_url + model + key.
    """

    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def send(
        self,
        messages: list[Message],
        tools: list[dict],
        max_tokens: int,
    ) -> Response:
        kwargs: dict = {
            "model": self.model,
            "messages": [m.to_api_dict() for m in messages],
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        completion = self.client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        msg = choice.message

        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for tc in (msg.tool_calls or [])
        ]

        raw: dict = {}
        if hasattr(completion, "model_dump"):
            try:
                raw = completion.model_dump()
            except Exception:
                pass

        return Response(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            raw=raw,
        )

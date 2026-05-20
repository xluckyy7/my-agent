import time
from typing import Iterator, Optional, Union

from my_agent.agent.context import ContextManager
from my_agent.agent.conversation import Conversation
from my_agent.agent.errors import AgentBudgetExceeded
from my_agent.agent.events import TurnTextDelta, TurnToolEnd, TurnToolStart
from my_agent.llm.client import LLMClient
from my_agent.llm.stream import assemble_stream
from my_agent.llm.types import TextDelta
from my_agent.tools.base import ToolRegistry

TurnEvent = Union[TurnTextDelta, TurnToolStart, TurnToolEnd]


class AgentLoop:
    """Generic ReAct-style multi-round loop.

    One run_turn() = one user input → possibly many (assistant ↔ tool) rounds
    → final assistant text. Loops until finish_reason is not "tool_calls" or
    max_iterations is hit.
    """

    def __init__(
        self,
        client: LLMClient,
        tools: ToolRegistry,
        max_iterations: int = 20,
        max_tokens: int = 4096,
        context_mgr: Optional[ContextManager] = None,
    ):
        self.client = client
        self.tools = tools
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.context_mgr = context_mgr

    def run_turn(self, conv: Conversation, user_input: str) -> str:
        conv.append_user(user_input)
        schemas = self.tools.get_schemas()

        for _ in range(self.max_iterations):
            if self.context_mgr is not None:
                self.context_mgr.maybe_compact(conv)
            conv.validate()  # local-fail-fast on protocol violations
            resp = self.client.send(
                messages=conv.messages,
                tools=schemas,
                max_tokens=self.max_tokens,
            )

            conv.append_assistant(
                content=resp.content,
                tool_calls=resp.tool_calls or None,
            )

            if resp.finish_reason == "tool_calls":
                for tc in resp.tool_calls:
                    result = self.tools.dispatch(tc.name, tc.arguments)
                    conv.append_tool_result(
                        tool_call_id=tc.id,
                        name=tc.name,
                        content=result.content,
                    )
                continue

            # stop, length, content_filter, or anything else: terminate
            return resp.content or ""

        raise AgentBudgetExceeded(
            f"exceeded {self.max_iterations} iterations without finish_reason=stop"
        )

    def run_turn_stream(
        self, conv: Conversation, user_input: str
    ) -> Iterator[TurnEvent]:
        """Streaming variant of run_turn.

        Yields TurnEvents as the turn unfolds:
          - TurnTextDelta: incremental text from the model
          - TurnToolStart: a tool is about to execute
          - TurnToolEnd:   a tool finished (content is the observation)

        The Conversation is mutated in place exactly like run_turn — same
        final state, just incremental output.

        Caller pattern:
            for ev in loop.run_turn_stream(conv, "..."):
                match ev:
                    case TurnTextDelta(text=t): print(t, end="", flush=True)
                    case TurnToolStart(name=n): print(f"\n▸ {n}")
                    case TurnToolEnd(is_error=err): ...
        """
        conv.append_user(user_input)
        schemas = self.tools.get_schemas()

        for _ in range(self.max_iterations):
            if self.context_mgr is not None:
                self.context_mgr.maybe_compact(conv)
            conv.validate()
            events = self.client.stream(
                messages=conv.messages,
                tools=schemas,
                max_tokens=self.max_tokens,
            )

            # Tee: yield text deltas to caller in realtime, also collect events
            # for assemble_stream to fold back into a Response after the stream
            # completes.
            collected = []
            for ev in events:
                collected.append(ev)
                if isinstance(ev, TextDelta):
                    yield TurnTextDelta(text=ev.text)

            resp = assemble_stream(iter(collected))

            conv.append_assistant(
                content=resp.content,
                tool_calls=resp.tool_calls or None,
            )

            if resp.finish_reason == "tool_calls":
                for tc in resp.tool_calls:
                    yield TurnToolStart(
                        tool_call_id=tc.id, name=tc.name, arguments=tc.arguments
                    )
                    started = time.monotonic()
                    result = self.tools.dispatch(tc.name, tc.arguments)
                    duration = time.monotonic() - started
                    yield TurnToolEnd(
                        tool_call_id=tc.id,
                        name=tc.name,
                        content=result.content,
                        is_error=result.is_error,
                        duration_seconds=duration,
                    )
                    conv.append_tool_result(
                        tool_call_id=tc.id,
                        name=tc.name,
                        content=result.content,
                    )
                continue

            # stop / length / content_filter / etc: terminate cleanly
            return

        raise AgentBudgetExceeded(
            f"exceeded {self.max_iterations} iterations without finish_reason=stop"
        )

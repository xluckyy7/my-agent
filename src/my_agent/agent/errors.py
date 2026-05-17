class AgentError(Exception):
    """Base class for all agent-domain errors."""


class AgentBudgetExceeded(AgentError):
    """Hit max_iterations without reaching finish_reason=stop."""


class ConversationInvalid(AgentError):
    """Conversation history violates an OpenAI-protocol invariant.

    Raised by Conversation.validate() before send() to surface the bug
    locally rather than as an opaque API 400 response.
    """

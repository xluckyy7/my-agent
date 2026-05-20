"""Web tools — web_fetch (no API key) and web_search (Tavily, optional)."""

import os

import httpx
import trafilatura

from .base import Tool

TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_SEARCH_MAX_RESULTS = 5

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MAX_CHARS = 8000
# Most public sites block default User-Agent. Pretend to be a generic browser.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 my-agent/0.6"
    )
}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated at {limit} chars]"


def _extract_main_text(html: str) -> str:
    """Use trafilatura to extract main article text from raw HTML.

    Falls back to the raw HTML (with tags) if extraction yields nothing —
    short pages and weird layouts sometimes defeat the extractor; raw is
    better than empty for the model.
    """
    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_recall=False,
    )
    return extracted or html


def _fetch(args: dict) -> str:
    url: str = args["url"]
    max_chars: int = int(args.get("max_chars") or DEFAULT_MAX_CHARS)

    with httpx.Client(
        headers=DEFAULT_HEADERS,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        resp = client.get(url)

    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")

    content_type = resp.headers.get("content-type", "").lower()
    body = resp.text

    if "html" in content_type:
        body = _extract_main_text(body)

    return _truncate(body, max_chars)


web_fetch_tool = Tool(
    name="web_fetch",
    description=(
        "Fetch a URL over HTTP(S) and return its text content. For HTML pages, "
        "extracts the main article body using trafilatura (strips nav, footer, "
        "ads, comments). For plain-text / JSON URLs, returns the raw body. "
        "Truncates to max_chars (default 8000) to keep tokens manageable. "
        "Use this when the user asks about a specific URL, web article, or "
        "online documentation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL including scheme (https://...)",
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    f"Maximum characters to return. Defaults to {DEFAULT_MAX_CHARS}. "
                    "Set lower for quick previews."
                ),
            },
        },
        "required": ["url"],
    },
    fn=_fetch,
)


# ===================================================================
# web_search — Tavily-backed. Requires TAVILY_API_KEY env var.
# Sign up free at https://tavily.com (1000 queries/month).
# ===================================================================


def _format_search_results(payload: dict, query: str) -> str:
    parts = [f'Search results for "{query}":\n']
    answer = (payload.get("answer") or "").strip()
    if answer:
        parts.append(f"DIRECT ANSWER: {answer}\n")
    results = payload.get("results") or []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        content = (r.get("content") or "").strip()
        parts.append(f"{i}. {title}\n   {url}\n   {content}\n")
    if not results:
        parts.append("(no results)")
    return "\n".join(parts)


def _search(args: dict) -> str:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY not set in environment. "
            "Sign up at https://tavily.com and add the key to your .env file."
        )

    query: str = args["query"]
    max_results: int = int(args.get("max_results") or DEFAULT_SEARCH_MAX_RESULTS)

    body = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": True,
    }

    with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        resp = client.post(TAVILY_ENDPOINT, json=body)

    if resp.status_code >= 400:
        raise RuntimeError(f"Tavily {resp.status_code}: {resp.text[:200]}")

    return _format_search_results(resp.json(), query)


web_search_tool = Tool(
    name="web_search",
    description=(
        "Search the web via Tavily and return the top results (title, URL, "
        "snippet) plus an optional direct answer. Use this when the user asks "
        "about current events, facts that may be outside the model's training "
        "data, comparisons, or anything where a quick web lookup helps. "
        "Combine with web_fetch to drill into specific URLs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (natural language is fine).",
            },
            "max_results": {
                "type": "integer",
                "description": (
                    f"Number of results to return. Defaults to {DEFAULT_SEARCH_MAX_RESULTS}."
                ),
            },
        },
        "required": ["query"],
    },
    fn=_search,
)

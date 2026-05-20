"""Web tools — web_fetch (no API key) and web_search (Tavily, optional)."""

import httpx
import trafilatura

from .base import Tool

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

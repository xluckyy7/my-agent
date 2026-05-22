"""Tests for web_fetch_tool — all httpx calls are mocked, never hit real network."""

from unittest.mock import MagicMock

import pytest

from my_agent.tools.web import web_fetch_tool


def _fake_response(*, status_code=200, text="", headers=None):
    """Build a MagicMock that mimics httpx.Response shape."""
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.headers = headers or {"content-type": "text/html; charset=utf-8"}
    r.raise_for_status = (
        lambda: (_ for _ in ()).throw(Exception(f"HTTP {status_code}"))
        if status_code >= 400
        else None
    )
    return r


def test_web_fetch_extracts_main_text_from_html(mocker):
    html = """
    <html><head><title>Demo</title></head>
    <body>
      <nav>SITE NAV</nav>
      <article>
        <h1>Title</h1>
        <p>This is the main article body. It has multiple sentences.</p>
        <p>Second paragraph with substantial content.</p>
      </article>
      <footer>COPYRIGHT FOOTER</footer>
    </body></html>
    """
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(text=html)

    out = web_fetch_tool.fn({"url": "https://example.com/article"})
    assert "main article body" in out
    # boilerplate-stripped:
    assert "COPYRIGHT FOOTER" not in out
    assert "SITE NAV" not in out


def test_web_fetch_returns_raw_text_for_plain_text(mocker):
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(
        text="just plain text\nline two",
        headers={"content-type": "text/plain"},
    )
    out = web_fetch_tool.fn({"url": "https://example.com/x.txt"})
    assert "just plain text" in out
    assert "line two" in out


def test_web_fetch_truncates_to_max_chars(mocker):
    long_html = "<html><body><p>" + ("blah " * 5000) + "</p></body></html>"
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(text=long_html)

    out = web_fetch_tool.fn({"url": "https://example.com/", "max_chars": 200})
    assert len(out) <= 250  # 200 + ellipsis marker margin
    assert "truncated" in out.lower() or "…" in out


def test_web_fetch_4xx_returns_body_with_status_prefix(mocker):
    """4xx responses must NOT raise — the body often contains the most
    useful info (404 page suggestions, error JSON, "moved to..." links).
    We return body prefixed with the status so the model can read both."""
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(
        status_code=404,
        text="<html><body><p>Page not found. Try /docs/ instead.</p></body></html>",
    )

    out = web_fetch_tool.fn({"url": "https://example.com/missing"})

    # Status visible to model
    assert "[HTTP 404]" in out
    assert "https://example.com/missing" in out
    # Body content preserved (model can act on the hint)
    assert "Try /docs/ instead" in out


def test_web_fetch_5xx_returns_body_with_status_prefix(mocker):
    """Same treatment for 5xx — body often contains an error JSON the model
    can use to construct a retry or report the issue."""
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(
        status_code=503,
        text='{"error":"upstream_down","retry_after":30}',
        headers={"content-type": "application/json"},
    )

    out = web_fetch_tool.fn({"url": "https://api.example.com/data"})

    assert "[HTTP 503]" in out
    assert "upstream_down" in out
    assert "retry_after" in out


def test_web_fetch_200_has_no_status_prefix(mocker):
    """Sanity: 200 responses must not get the [HTTP NNN] prefix added."""
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(
        text="<html><body><p>Normal content here</p></body></html>"
    )

    out = web_fetch_tool.fn({"url": "https://example.com/"})

    assert "[HTTP" not in out
    assert "Normal content here" in out


def test_web_fetch_passes_url_to_client(mocker):
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(text="<html><body><p>x</p></body></html>")

    web_fetch_tool.fn({"url": "https://example.com/page"})
    fake_get.assert_called_once()
    assert fake_get.call_args.args[0] == "https://example.com/page"


def test_web_fetch_sets_user_agent(mocker):
    """Many sites block default httpx UA. We send a friendlier one."""
    fake_client_cls = mocker.patch("my_agent.tools.web.httpx.Client")
    fake_client = fake_client_cls.return_value.__enter__.return_value
    fake_client.get.return_value = _fake_response(text="<p>x</p>")

    web_fetch_tool.fn({"url": "https://example.com/"})
    init_kwargs = fake_client_cls.call_args.kwargs
    assert "headers" in init_kwargs
    assert "User-Agent" in init_kwargs["headers"]


def test_web_fetch_schema_shape():
    s = web_fetch_tool.parameters
    assert s["type"] == "object"
    assert "url" in s["properties"]
    assert s["properties"]["url"]["type"] == "string"
    assert "max_chars" in s["properties"]
    assert s["required"] == ["url"]


def test_web_fetch_metadata():
    assert web_fetch_tool.name == "web_fetch"
    assert web_fetch_tool.description
    assert callable(web_fetch_tool.fn)


def test_web_fetch_via_registry_dispatch_error(mocker):
    """Network error → Registry catches → is_error=True ToolResult."""
    from my_agent.tools.base import ToolRegistry

    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.side_effect = Exception("Connection refused")

    reg = ToolRegistry()
    reg.register(web_fetch_tool)
    res = reg.dispatch("web_fetch", '{"url": "https://broken.example.com/"}')
    assert res.is_error is True
    assert "refused" in res.content.lower() or "connection" in res.content.lower()


# ---------------- web_search (Tavily) ----------------


def _fake_tavily_response(results=None, answer=""):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        "query": "test query",
        "answer": answer,
        "results": results or [],
    }
    r.raise_for_status = lambda: None
    return r


def test_web_search_calls_tavily_with_query_and_key(mocker, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-fake-key")
    fake_post = mocker.patch("my_agent.tools.web.httpx.Client.post")
    fake_post.return_value = _fake_tavily_response(
        results=[{"title": "T1", "url": "https://a.com", "content": "snippet 1"}]
    )

    from my_agent.tools.web import web_search_tool

    out = web_search_tool.fn({"query": "what is rust"})
    fake_post.assert_called_once()
    call = fake_post.call_args
    body = call.kwargs.get("json") or call.args[1]
    assert body["query"] == "what is rust"
    assert body["api_key"] == "tvly-fake-key"
    assert "T1" in out
    assert "https://a.com" in out
    assert "snippet 1" in out


def test_web_search_formats_multiple_results(mocker, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    fake_post = mocker.patch("my_agent.tools.web.httpx.Client.post")
    fake_post.return_value = _fake_tavily_response(
        results=[
            {"title": f"Title {i}", "url": f"https://x.com/{i}", "content": f"snippet {i}"}
            for i in range(5)
        ]
    )
    from my_agent.tools.web import web_search_tool

    out = web_search_tool.fn({"query": "anything"})
    for i in range(5):
        assert f"Title {i}" in out
        assert f"https://x.com/{i}" in out


def test_web_search_includes_tavily_answer_when_present(mocker, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    fake_post = mocker.patch("my_agent.tools.web.httpx.Client.post")
    fake_post.return_value = _fake_tavily_response(
        answer="Rust is a systems programming language.",
        results=[{"title": "x", "url": "https://x.com", "content": "y"}],
    )
    from my_agent.tools.web import web_search_tool

    out = web_search_tool.fn({"query": "rust"})
    assert "Rust is a systems programming language" in out


def test_web_search_missing_key_raises(mocker, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from my_agent.tools.web import web_search_tool

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        web_search_tool.fn({"query": "anything"})


def test_web_search_passes_max_results(mocker, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    fake_post = mocker.patch("my_agent.tools.web.httpx.Client.post")
    fake_post.return_value = _fake_tavily_response(results=[])
    from my_agent.tools.web import web_search_tool

    web_search_tool.fn({"query": "x", "max_results": 3})
    body = fake_post.call_args.kwargs["json"]
    assert body["max_results"] == 3


def test_web_search_schema_shape():
    from my_agent.tools.web import web_search_tool

    s = web_search_tool.parameters
    assert s["type"] == "object"
    assert "query" in s["properties"]
    assert s["required"] == ["query"]


def test_web_search_metadata():
    from my_agent.tools.web import web_search_tool

    assert web_search_tool.name == "web_search"
    assert web_search_tool.description

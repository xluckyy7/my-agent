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


def test_web_fetch_non_200_returns_error(mocker):
    fake_get = mocker.patch("my_agent.tools.web.httpx.Client.get")
    fake_get.return_value = _fake_response(status_code=404, text="Not Found")

    # The tool itself raises; ToolRegistry.dispatch converts to is_error
    with pytest.raises(Exception, match="404"):
        web_fetch_tool.fn({"url": "https://example.com/missing"})


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

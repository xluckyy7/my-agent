import io

from my_agent.cli.render import CYAN, RESET, color, truncate


def test_truncate_short_unchanged():
    assert truncate("hello", 10) == "hello"


def test_truncate_long_with_ellipsis():
    out = truncate("a" * 200, 10)
    assert len(out) == 10
    assert out.endswith("…")


def test_truncate_collapses_whitespace():
    """Multi-line and tabs get flattened so previews stay one-line."""
    assert truncate("a\nb\t  c") == "a b c"


def test_color_no_tty_returns_plain():
    """piped output (StringIO) is not a TTY → no escape codes."""
    s = io.StringIO()
    out = color("hi", CYAN, stream=s)
    assert out == "hi"
    assert "\x1b[" not in out


def test_color_tty_wraps_with_escapes(monkeypatch):
    """Fake TTY-like stream to verify ANSI gets added."""

    class FakeTTY:
        def isatty(self):
            return True

    out = color("hi", CYAN, stream=FakeTTY())
    assert out.startswith(CYAN)
    assert out.endswith(RESET)
    assert "hi" in out

import pytest

from my_agent.config import Config, load_config


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("DEFAULT_MODEL", "qwen-plus")
    cfg = load_config()
    assert cfg.api_key == "test-key"
    assert cfg.base_url == "https://example.com/v1"
    assert cfg.model == "qwen-plus"


def test_load_config_missing_key_raises(monkeypatch, tmp_path, chdir):
    chdir(tmp_path)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        load_config()


def test_config_defaults():
    cfg = Config(api_key="k")
    assert cfg.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.model == "qwen-plus"
    assert cfg.max_tokens == 4096
    assert cfg.context_budget == 8000
    assert cfg.keep_recent_turns == 4


def test_load_config_context_overrides(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    monkeypatch.setenv("CONTEXT_BUDGET", "16000")
    monkeypatch.setenv("KEEP_RECENT_TURNS", "8")
    cfg = load_config()
    assert cfg.context_budget == 16000
    assert cfg.keep_recent_turns == 8

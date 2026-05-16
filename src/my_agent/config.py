import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv


@dataclass
class Config:
    api_key: str
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    max_tokens: int = 4096


def load_config() -> Config:
    # usecwd=True so .env is found relative to where the user runs the tool,
    # not relative to where this source file lives. Important for testability
    # (chdir-based isolation works) and intuitive for users.
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DASHSCOPE_API_KEY not set. Copy .env.example to .env and fill in your key."
        )
    return Config(
        api_key=api_key,
        base_url=os.environ.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        model=os.environ.get("DEFAULT_MODEL", "qwen-plus"),
    )

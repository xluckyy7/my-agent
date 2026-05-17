from pathlib import Path

from .base import Tool


def _read_file(args: dict) -> str:
    return Path(args["path"]).read_text(encoding="utf-8")


read_file_tool = Tool(
    name="read_file",
    description=(
        "Read a UTF-8 text file from the local filesystem and return its full "
        "contents as a string. Use this when you need to inspect file contents "
        "before answering or making changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative file path",
            }
        },
        "required": ["path"],
    },
    fn=_read_file,
)

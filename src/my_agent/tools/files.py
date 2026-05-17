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


def _write_file(args: dict) -> str:
    p = Path(args["path"])
    content: str = args["content"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content.encode('utf-8'))} bytes to {p}"


write_file_tool = Tool(
    name="write_file",
    description=(
        "Write text content to a file on the local filesystem. Creates parent "
        "directories if missing. OVERWRITES existing files without warning. "
        "Use this when the user asks to save, create, or update a file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Target file path (absolute or relative).",
            },
            "content": {
                "type": "string",
                "description": "Full file contents to write (UTF-8).",
            },
        },
        "required": ["path", "content"],
    },
    fn=_write_file,
)

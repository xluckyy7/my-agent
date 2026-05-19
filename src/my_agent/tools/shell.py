import subprocess
from pathlib import Path

from .base import Tool

DEFAULT_TIMEOUT_SECONDS = 30


def _run_bash(args: dict) -> str:
    command: str = args["command"]
    timeout: int = int(args.get("timeout") or DEFAULT_TIMEOUT_SECONDS)

    # subprocess.run will raise TimeoutExpired on timeout; ToolRegistry.dispatch
    # catches it and produces an is_error=True ToolResult that the model sees.
    result = subprocess.run(
        command,
        shell=True,
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    parts: list[str] = [f"exit code: {result.returncode}"]
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    return "\n\n".join(parts)


run_bash_tool = Tool(
    name="run_bash",
    description=(
        "Run a shell command via /bin/sh -c and return its exit code, stdout, "
        "and stderr. The command runs in the current working directory of the "
        "agent process. Has a default 30s timeout to prevent hangs. Use this "
        "for builds, tests, file searches (grep/find/ls), git commands, package "
        "managers, or any one-shot CLI task. Do NOT use it for long-running "
        "servers — there's no streaming or process management."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The full shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": (
                    f"Max seconds to wait before the command is killed. "
                    f"Defaults to {DEFAULT_TIMEOUT_SECONDS}."
                ),
            },
        },
        "required": ["command"],
    },
    fn=_run_bash,
)

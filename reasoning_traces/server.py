"""Reasoning Traces — MCP server exposing a stronger reasoning model.

The coding agent calls the deep_reasoning tool with a problem statement and
the context it has gathered; the tool returns the stronger model's reasoning
trace, which the agent then uses to shape its answer.
"""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .backends import get_backend


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a .env in the working directory, so
    secrets like OPENROUTER_API_KEY don't have to live in shell profiles
    or shareable MCP configs. Existing environment variables win."""
    path = Path.cwd() / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


mcp = FastMCP("reasoning-traces")

# Claude Code warns when a tool result exceeds ~10k tokens; keep the default
# response comfortably under that (~4 chars/token).
MAX_RESULT_CHARS = int(os.environ.get("REASONING_MAX_RESULT_CHARS", "32000"))

_backend = None


def _get_backend():
    # Lazy init so the server starts (and lists tools) even before
    # backend credentials are configured.
    global _backend
    if _backend is None:
        _backend = get_backend()
    return _backend


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.7), int(limit * 0.25)
    elided = len(text) - head - tail
    return f"{text[:head]}\n\n[... {elided} characters elided ...]\n\n{text[-tail:]}"


@mcp.tool()
def deep_reasoning(problem: str, context: str = "", constraints: str = "") -> str:
    """Consult a stronger reasoning model and get its full reasoning trace.

    Call this BEFORE proposing a solution whenever the task involves
    multi-step reasoning: subtle bugs or race conditions, architectural
    trade-offs, algorithm design, math, or anything where a first instinct
    could be wrong. Use the returned trace to guide and cross-check your
    own answer.

    The reasoning model cannot see this conversation — pass everything it
    needs.

    Args:
        problem: The question or task, stated precisely.
        context: Relevant code, error output, logs, or background you have
            gathered. Include full snippets, not paraphrases.
        constraints: Hard requirements the solution must satisfy
            (performance, compatibility, style), if any.
    """
    prompt_parts = [problem]
    if context:
        prompt_parts.append(f"<context>\n{context}\n</context>")
    if constraints:
        prompt_parts.append(f"<constraints>\n{constraints}\n</constraints>")
    prompt_parts.append(
        "Reason through this carefully, then give your conclusion and recommendation."
    )

    result = _get_backend().reason("\n\n".join(prompt_parts))

    sections = []
    if result.trace:
        sections.append(f"## Reasoning trace\n\n{result.trace}")
    if result.conclusion:
        sections.append(f"## Conclusion\n\n{result.conclusion}")
    if not sections:
        return "The reasoning model returned no output."
    return _truncate("\n\n".join(sections), MAX_RESULT_CHARS)


def main() -> None:
    _load_dotenv()
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()

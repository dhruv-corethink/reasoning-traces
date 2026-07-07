"""Reasoning backends for Reasoning Traces.

A backend takes a fully-composed prompt and returns a ReasoningResult:
the model's reasoning trace plus its final conclusion. Select one with
the REASONING_BACKEND env var ("openrouter" | "anthropic" | "corethink",
default "openrouter").
"""

import os
from dataclasses import dataclass


@dataclass
class ReasoningResult:
    trace: str
    conclusion: str


class OpenRouterBackend:
    """Default backend: any reasoning model on OpenRouter, via its
    OpenAI-compatible API.

    Uses OpenRouter's unified `reasoning` parameter. Models like
    deepseek/deepseek-r1 return their full raw reasoning trace in
    `message.reasoning`; others (o3, gemini) return summaries.
    """

    def __init__(self) -> None:
        import httpx

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Get a key at openrouter.ai "
                "and export it in your shell (or put it in a .env file in "
                "your project directory)."
            )
        self.model = os.environ.get("REASONING_MODEL", "deepseek/deepseek-r1-0528")
        self.effort = os.environ.get("REASONING_EFFORT", "high")
        self.max_tokens = int(os.environ.get("REASONING_MAX_TOKENS", "32000"))
        self.client = httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(600.0, connect=15.0),
        )

    def reason(self, prompt: str) -> ReasoningResult:
        response = self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self.max_tokens,
                "reasoning": {"effort": self.effort},
            },
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]

        trace = message.get("reasoning") or ""
        if not trace:
            # Some models report reasoning as structured detail blocks instead.
            details = message.get("reasoning_details") or []
            trace = "\n\n".join(
                filter(None, (d.get("text") or d.get("summary") for d in details))
            )
        return ReasoningResult(trace=trace, conclusion=message.get("content") or "")


class AnthropicBackend:
    """Claude Opus 4.8 with adaptive thinking.

    The Anthropic API never returns the raw chain of thought;
    display="summarized" returns a readable summary of the reasoning,
    which serves as the trace.
    """

    def __init__(self) -> None:
        import anthropic

        # Resolves credentials from ANTHROPIC_API_KEY or an `ant auth login`
        # profile automatically.
        self.client = anthropic.Anthropic()
        self.model = os.environ.get("REASONING_MODEL", "claude-opus-4-8")
        self.effort = os.environ.get("REASONING_EFFORT", "xhigh")
        self.max_tokens = int(os.environ.get("REASONING_MAX_TOKENS", "64000"))

    def reason(self, prompt: str) -> ReasoningResult:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            category = (
                message.stop_details.category if message.stop_details else "unknown"
            )
            return ReasoningResult(
                trace="",
                conclusion=f"The reasoning model declined this request (category: {category}).",
            )

        trace = "\n\n".join(
            block.thinking
            for block in message.content
            if block.type == "thinking" and block.thinking
        )
        conclusion = "\n\n".join(
            block.text for block in message.content if block.type == "text"
        )
        return ReasoningResult(trace=trace, conclusion=conclusion)


class CorethinkBackend:
    """Stub for the Corethink reasoning model.

    Implement the API call in reason(): send `prompt` to the model, then
    return ReasoningResult(trace=<its reasoning trace>,
    conclusion=<its final answer>).
    """

    def __init__(self) -> None:
        self.api_url = os.environ.get("CORETHINK_API_URL", "")
        self.api_key = os.environ.get("CORETHINK_API_KEY", "")

    def reason(self, prompt: str) -> ReasoningResult:
        raise NotImplementedError(
            "CorethinkBackend is a stub — implement the API call in "
            "reasoning_traces/backends.py::CorethinkBackend.reason()"
        )


def get_backend():
    name = os.environ.get("REASONING_BACKEND", "openrouter").lower()
    backends = {
        "openrouter": OpenRouterBackend,
        "anthropic": AnthropicBackend,
        "corethink": CorethinkBackend,
    }
    if name not in backends:
        raise ValueError(
            f"Unknown REASONING_BACKEND {name!r}; expected one of {sorted(backends)}"
        )
    return backends[name]()

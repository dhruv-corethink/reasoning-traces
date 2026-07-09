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
        self.model = os.environ.get("REASONING_MODEL", "anthropic/claude-opus-4.8")
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
    """The CoreThink reasoning endpoint.

    Calls the CoreThink proxy (hosted on Cloud Run), which holds the upstream
    provider URL, model, and key server-side. The client only needs a
    CoreThink API key — export CORETHINK_API_KEY and go. The reasoning model
    is selected server-side (Claude Opus 4.8 by default). Its reasoning arrives
    either as a `reasoning` field or inline as <think>...</think>; this backend
    handles both, splitting the trace from the final conclusion.
    """

    DEFAULT_BASE_URL = "https://corethink-reason-proxy-xfsavzevuq-uc.a.run.app"

    def __init__(self) -> None:
        import httpx

        api_key = os.environ.get("CORETHINK_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "CORETHINK_API_KEY is not set. Export the CoreThink API key you "
                "were issued, e.g. `export CORETHINK_API_KEY=ct-...`."
            )
        self.base_url = os.environ.get("CORETHINK_BASE_URL", self.DEFAULT_BASE_URL).rstrip("/")
        self.effort = os.environ.get("REASONING_EFFORT", "high")
        self.max_tokens = int(os.environ.get("REASONING_MAX_TOKENS", "32000"))
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(600.0, connect=15.0),
        )

    def reason(self, prompt: str) -> ReasoningResult:
        import re

        # The proxy forces the model server-side; no model is sent from here.
        response = self.client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self.max_tokens,
                "reasoning": {"effort": self.effort},
            },
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]

        # Prefer explicit reasoning fields if the upstream provides them;
        # otherwise split the DeepSeek-R1-style inline <think>...</think>.
        trace = message.get("reasoning") or message.get("reasoning_content") or ""
        content = message.get("content") or ""
        if not trace and "<think>" in content:
            m = re.search(r"<think>(.*?)</think>(.*)", content, re.DOTALL)
            if m:
                trace, content = m.group(1), m.group(2)
            else:  # opened but never closed (truncated) — it's all trace
                trace, content = content.split("<think>", 1)[1], ""
        return ReasoningResult(trace=trace.strip(), conclusion=content.strip())


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

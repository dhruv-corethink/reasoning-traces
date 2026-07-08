# Reasoning Traces

**Give your coding agent a stronger brain to consult.**

Reasoning Traces is an MCP server + Claude Code plugin. It adds a `deep_reasoning` tool: the agent sends a hard problem (plus the code and context it has gathered) to a stronger reasoning model, gets back the model's **full reasoning trace**, and uses that trace to shape and cross-check its own answer.

Works out of the box with reasoning models on [OpenRouter](https://openrouter.ai) (default: Claude Opus 4.8; one env var switches to DeepSeek R1 for full raw chain-of-thought traces, o3, Gemini, or any other slug). Anthropic and custom backends included.

## Install (Claude Code)

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and an [OpenRouter API key](https://openrouter.ai/keys).

1. Export your key (add to `~/.zshrc` / `~/.bashrc` to persist):

   ```sh
   export OPENROUTER_API_KEY=sk-or-v1-...
   ```

2. In Claude Code:

   ```
   /plugin marketplace add dhruv-corethink/reasoning-traces
   /plugin install reasoning-traces@corethink
   ```

3. Restart Claude Code (or start a new session). Done — the plugin works in **every** project.

Verify with `/mcp` (the `reasoning-traces` server should be connected).

## Usage

- **Automatic** — Claude Code calls `deep_reasoning` on its own when a task involves multi-step reasoning (subtle bugs, architecture trade-offs, algorithm design, math). The tool description steers this.
- **On demand** — force a consultation:

  ```
  /reason why does this async queue deadlock under load?
  ```

The tool result contains the reasoning model's full trace plus its conclusion; Claude Code verifies it against your actual code before answering.

## Team rollout (zero-command install)

Add this to a shared repo's `.claude/settings.json` and every teammate gets the plugin automatically when they trust the workspace:

```json
{
  "extraKnownMarketplaces": {
    "corethink": {
      "source": { "source": "github", "repo": "dhruv-corethink/reasoning-traces" }
    }
  },
  "enabledPlugins": { "reasoning-traces@corethink": true }
}
```

Each teammate still needs their own `OPENROUTER_API_KEY` in their environment.

## Configuration

Set env vars in your shell, or per-project in a `.env` file (the server loads `.env` from the working directory; existing env vars win).

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required for the default backend |
| `REASONING_BACKEND` | `openrouter` | `openrouter`, `anthropic`, or `corethink` |
| `REASONING_MODEL` | `anthropic/claude-opus-4.8` | Any OpenRouter model slug (e.g. `deepseek/deepseek-r1-0528`, `openai/o3`); `claude-opus-4-8` for the anthropic backend |
| `REASONING_EFFORT` | `high` | openrouter: `low`/`medium`/`high`; anthropic: up to `xhigh`/`max` |
| `REASONING_MAX_TOKENS` | `32000` | Output cap for the reasoning call |
| `REASONING_MAX_RESULT_CHARS` | `32000` | Truncation cap on the tool result |

Claude Opus 4.8 is the default. Note: Anthropic models (and o3/Gemini) return **summarized** reasoning; for a full raw chain of thought, set `REASONING_MODEL=deepseek/deepseek-r1-0528`.

## Other MCP clients

Any MCP client (Claude Desktop, Cursor, etc.) can run the server without the plugin:

```json
{
  "mcpServers": {
    "reasoning-traces": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/dhruv-corethink/reasoning-traces", "reasoning-traces"],
      "env": { "OPENROUTER_API_KEY": "sk-or-v1-..." }
    }
  }
}
```

Or with plain Claude Code CLI, no plugin:

```sh
claude mcp add --scope user reasoning-traces -- uvx --from git+https://github.com/dhruv-corethink/reasoning-traces reasoning-traces
```

## Custom backends

`reasoning_traces/backends.py` defines a tiny interface — `reason(prompt) -> ReasoningResult(trace, conclusion)`. Three backends ship today:

- **`openrouter`** (default) — any reasoning model on OpenRouter
- **`anthropic`** — Claude Opus 4.8 with adaptive thinking (summarized reasoning; the Anthropic API never exposes raw chain of thought)
- **`corethink`** — stub for the Corethink reasoning model (coming soon)

## Development

```sh
git clone https://github.com/dhruv-corethink/reasoning-traces
cd reasoning-traces
echo "OPENROUTER_API_KEY=sk-or-v1-..." > .env   # gitignored
```

Open Claude Code in the repo — `.mcp.json` runs the server straight from source via `uvx`. The `.env` is loaded by the server at startup.

## License

MIT

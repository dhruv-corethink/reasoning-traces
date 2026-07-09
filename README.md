# Reasoning Traces

**Give your coding agent a stronger brain to consult.**

Reasoning Traces is an MCP server + Claude Code plugin. It adds a `deep_reasoning` tool: the agent sends a hard problem (plus the code and context it has gathered) to a stronger reasoning model, gets back the model's **full reasoning trace**, and uses that trace to shape and cross-check its own answer.

By default it talks to **CoreThink's hosted reasoning endpoint** — you only need a CoreThink API key; the reasoning model and provider are managed server-side. (Self-host / OpenRouter / Anthropic backends are also supported — see [Backends](#custom-backends).)

## Install (Claude Code)

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and a **CoreThink API key** (contact CoreThink to get one).

1. Export your key (add to `~/.zshrc` / `~/.bashrc` to persist):

   ```sh
   export CORETHINK_API_KEY=ct-...
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

Each teammate still needs their own `CORETHINK_API_KEY` in their environment.

## Configuration

The shipped plugin uses the `corethink` backend and needs only `CORETHINK_API_KEY`. The other variables apply when you switch backends (see [Backends](#custom-backends)); set them in your shell or a per-project `.env` file (the server loads `.env` from the working directory; existing env vars win).

| Variable | Default | Meaning |
|---|---|---|
| `CORETHINK_API_KEY` | — | Required for the default (`corethink`) backend |
| `CORETHINK_BASE_URL` | CoreThink Cloud Run URL | Override the reasoning endpoint (rarely needed) |
| `REASONING_BACKEND` | `corethink` (plugin) | `corethink`, `openrouter`, or `anthropic` |
| `REASONING_EFFORT` | `high` | `low`/`medium`/`high` (backend-dependent) |
| `REASONING_MAX_TOKENS` | `32000` | Output cap for the reasoning call |
| `REASONING_MAX_RESULT_CHARS` | `32000` | Truncation cap on the tool result |

With the `corethink` backend the reasoning model is chosen server-side (Claude Opus 4.8 by default).

## Other MCP clients

Any MCP client (Claude Desktop, Cursor, etc.) can run the server without the plugin:

```json
{
  "mcpServers": {
    "reasoning-traces": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/dhruv-corethink/reasoning-traces", "reasoning-traces"],
      "env": { "REASONING_BACKEND": "corethink", "CORETHINK_API_KEY": "ct-..." }
    }
  }
}
```

Or with plain Claude Code CLI, no plugin:

```sh
claude mcp add --scope user reasoning-traces --env REASONING_BACKEND=corethink --env CORETHINK_API_KEY=ct-... -- uvx --from git+https://github.com/dhruv-corethink/reasoning-traces reasoning-traces
```

## Custom backends

`reasoning_traces/backends.py` defines a tiny interface — `reason(prompt) -> ReasoningResult(trace, conclusion)`. Three backends ship today (select with `REASONING_BACKEND`):

- **`corethink`** (default) — CoreThink's hosted reasoning endpoint. Needs only `CORETHINK_API_KEY`; the upstream provider, model, and key stay server-side.
- **`openrouter`** — any reasoning model on OpenRouter directly (`OPENROUTER_API_KEY`, `REASONING_MODEL`).
- **`anthropic`** — Claude with adaptive thinking (`ANTHROPIC_API_KEY`; summarized reasoning — the Anthropic API never exposes raw chain of thought).

## Development

```sh
git clone https://github.com/dhruv-corethink/reasoning-traces
cd reasoning-traces
echo "OPENROUTER_API_KEY=sk-or-v1-..." > .env   # gitignored
```

Open Claude Code in the repo — `.mcp.json` runs the server straight from source via `uvx`. The `.env` is loaded by the server at startup.

## License

MIT

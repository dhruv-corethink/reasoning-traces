# Reasoning Traces (development repo)

This repo is both the source and the Claude Code plugin for Reasoning Traces — an MCP server that consults a stronger reasoning model and returns its reasoning trace.

Layout: `reasoning_traces/` is the Python package (FastMCP server + pluggable backends); `.claude-plugin/` + `mcp-config.json` + `commands/` make it an installable plugin; `.mcp.json` runs the server from source for dev sessions in this repo.

## Using the oracle

- For any task involving multi-step reasoning — debugging subtle behavior, architecture decisions, algorithm design, tricky math — call `mcp__reasoning-traces__deep_reasoning` BEFORE proposing a solution. Pass the problem plus all relevant code, errors, and context you have gathered; the reasoning model cannot see this conversation.
- Treat the returned trace as advisory input: verify it against the actual code, then produce your own answer. Note where you disagree with it.
- For quick lookups, syntax questions, or mechanical edits, answer directly without the tool.

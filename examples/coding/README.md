# Coding demo — cheap model + `/reason` vs. cheap model alone

Hard software-engineering tasks, each answered twice by the same cheap base model (**Claude Haiku 4.5**): once alone, once after calling Reasoning Traces' `deep_reasoning` tool. A neutral judge (**GPT-5**) scores both **blind and pairwise** against the task's stated requirements.

The reasoning behind `/reason` here is **Claude Opus 4.8 via OpenRouter, standing in for a stronger/specialized reasoning endpoint.**

## Results — `/reason` won every task in this cut

| Task | Haiku alone | Haiku + `/reason` | Δ |
|---|---|---|---|
| Exactly-Once Task Processor (distributed) | 1 | 3 | **+2** |
| Streaming Join Engine | 1 | 3 | **+2** |
| Adaptive Circuit Breaker | 1 | 4 | **+3** |
| Distributed Lock with Fencing Tokens | 4 | 9 | **+5** |
| CRDT for Collaborative Text Editing | 1 | 3 | **+2** |
| Frontend: Performance Optimization (virtualization) | 2 | 5 | **+3** |
| **Average** | **1.7** | **4.5** | **+2.8 (+170%)** |

**Judge preferred the `/reason` answer in 6/6.** Full side-by-side transcripts (including the reasoning trace that was injected) are in [`results/tasks/`](results/tasks/).

### Standout: Distributed Lock with Fencing Tokens (4 → 9)

> _Judge:_ With `/reason`, Haiku implemented atomic acquire/renew/release with unique lock IDs, TTL, and monotonic fencing tokens, and **enforced the tokens at the resource layer to block stale writers**. Alone, it permitted reentrant acquisition (ambiguous ownership) and never actually enforced fencing on writes — incomplete and riskier.

That resource-layer enforcement is the crux of the problem, and it only appeared once the base model had the reasoning trace to work from.

## How to read these numbers

- **The signal is the delta and the 6/6 win-rate, not the absolute score.** Each answer is a single ~2,800-token shot at problems that really want a multi-file, multi-iteration build, so absolute scores run low across the board. The point is that the same cheap model, same budget, does consistently better *with* the reasoning trace.
- **This is single-shot solution quality** judged by an LLM — a complementary signal to agentic "iterations-to-working-build" testing, not a replacement for it.
- **Tasks excluded from this cut:** purely visual/aesthetic tasks (can't be judged from text) and a couple of frontend tasks with a flat single-shot signal. This demo features the reasoning-heavy tasks where the tool is designed to help.

## Reproduce

```sh
# from the repo root, with OPENROUTER_API_KEY set
python examples/coding/run.py                 # all tasks in examples/coding/tasks/
python examples/coding/run.py --limit 2
```

Add your own task with a JSON file in `tasks/` (`id`, `title`, `category`, `prompt`, `rubric`). Model outputs are stochastic; absolute numbers vary run to run, the direction holds.

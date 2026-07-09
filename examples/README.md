# Reasoning Traces — demos

Evidence that a cheap, fast base model reaches near–frontier quality on hard problems when it can escalate to a stronger reasoning model through the `/reason` tool — instead of paying for the expensive model on every request.

Each demo runs the same base model **twice** per task:

- **WITHOUT** — the base model answers alone.
- **WITH** — the base model answers after receiving the reasoning trace from Reasoning Traces' `deep_reasoning` tool (the plugin's real behavior).

A neutral judge (a different model family) then scores both answers **blind and pairwise** against a fixed reference answer.

## Salesforce demo

The customer's domain is Salesforce, and their goal is to run a cheap base model (**Claude Haiku 4.5**) and lift its quality with `/reason`. This suite is five Salesforce/Apex problems with subtle, verifiable expert answers: trigger bulkification & governor limits, sync-vs-async limit math, a `NOT IN` semi-join, a `Database.Stateful` batch bug, and CPQ proration math.

### Results

<!-- RESULTS:START -->
**Latest run** — base **Claude Haiku 4.5**, reasoning **Claude Opus 4.8**, judge **openai/gpt-5** (blind):

| | Avg score /10 |
|---|---|
| Claude Haiku 4.5 alone | **6.0** |
| Claude Haiku 4.5 + Reasoning Traces | **8.8** |

Judge preferred the reasoning-assisted answer in **3/5** tasks. Uplift **+2.8 points**.

| Task | Without | With | Δ |
|---|---|---|---|
| Apex trigger: bulkification & governor limits | 6 | 10 | +4 |
| Batch Apex governor-limit math (sync vs async) | 5 | 4 | -1 |
| SOQL: Accounts with zero Opportunities | 7 | 10 | +3 |
| Batch Apex: wrong running total | 2 | 10 | +8 |
| CPQ: prorated + discounted add-on | 10 | 10 | +0 |

Full transcripts: [`results/summary.md`](results/summary.md).
<!-- RESULTS:END -->

### Reading the results

- **Where it helps most:** the subtle, reasoning-heavy tasks. The `Database.Stateful` batch bug went **2 → 10** and the `NOT IN` semi-join **7 → 10** — Haiku alone missed the root cause; the trace supplied it.
- **Where it's a wash:** problems Haiku already handles well (straightforward proration math) stay flat — the trace neither helps nor hurts, and you've spent one reasoning call for no gain. This is expected and is why `/reason` is an *escalation* tool, not an always-on wrapper.
- **The one regression is the most instructive result.** On the async governor-limit task, the reasoning model *itself* got a genuinely obscure fact wrong (it cited the synchronous 100-query SOQL limit; Batch Apex runs asynchronously with a 200 limit and actually fails on DML), and Haiku faithfully propagated the error. The neutral judge caught it. **The ceiling is the reasoning model's own knowledge** — which is exactly the argument for plugging in a stronger or domain-specialized reasoning model (a higher `REASONING_EFFORT`, a frontier model, or your own fine-tuned Salesforce model) behind the same tool.

## Run it yourself

```sh
# from the repo root, with OPENROUTER_API_KEY in .env or the environment
python examples/run_demo.py                 # all tasks
python examples/run_demo.py --limit 2       # quick check (first 2 tasks)
```

Configurable via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `BASE_MODEL` | `anthropic/claude-haiku-4.5` | The cheap/fast model being lifted |
| `REASONING_MODEL` | `anthropic/claude-opus-4.8` | The reasoning model behind `deep_reasoning` |
| `JUDGE_MODEL` | `openai/gpt-5` | Neutral blind judge |

Outputs are written to `results/`: `summary.md` (headline + table), `results.json` (raw scores), and `tasks/<id>.md` (full transcript per task, including the reasoning trace that was supplied).

## Adding your own tasks

Drop a JSON file in `tasks/` with these fields: `id`, `title`, `category`, `prompt`, `reference` (ground-truth answer), and `rubric` (list of scored criteria). Re-run the harness. Real customer tasks — a Salesforce org's actual Apex, flows, or SOQL — slot in the same way.

> Model outputs are stochastic; absolute scores vary run to run. The consistent finding is the direction and size of the uplift, not the exact numbers.

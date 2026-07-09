#!/usr/bin/env python3
"""Reasoning Traces — with/without demo harness.

For each task it runs two conditions:

  WITHOUT  — the base model (Haiku) answers the task directly.
  WITH     — the same base model answers, but first receives the reasoning
             trace produced by Reasoning Traces' deep_reasoning tool
             (the OpenRouter backend, default model Claude Opus 4.8).

A neutral judge (a different model family — GPT-5) then scores both answers
blind and pairwise against a fixed reference answer, so the comparison
isn't biased toward the Anthropic-powered condition.

Outputs land in examples/results/:
  results.json            machine-readable scores
  summary.md              headline + per-task table
  tasks/<id>.md           full transcript for each task

Requires OPENROUTER_API_KEY (read from the repo's .env or the environment).

Usage:
  python examples/run_demo.py                 # all tasks
  python examples/run_demo.py --limit 2       # first 2 tasks (quick check)
  BASE_MODEL=anthropic/claude-3-haiku python examples/run_demo.py
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

# Import the plugin's own reasoning backend so the demo genuinely exercises
# what ships in the product, rather than reimplementing the reasoning call.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from reasoning_traces.backends import OpenRouterBackend  # noqa: E402

EXAMPLES_DIR = Path(__file__).resolve().parent
TASKS_DIR = EXAMPLES_DIR / "tasks"
RESULTS_DIR = EXAMPLES_DIR / "results"

BASE_MODEL = os.environ.get("BASE_MODEL", "anthropic/claude-haiku-4.5")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "openai/gpt-5")
BASE_LABEL = os.environ.get("BASE_LABEL", "Claude Haiku 4.5")
REASONING_LABEL = os.environ.get("REASONING_LABEL", "Claude Opus 4.8")


def _load_dotenv() -> None:
    path = REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class OpenRouter:
    def __init__(self) -> None:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            sys.exit("OPENROUTER_API_KEY is not set (put it in the repo's .env).")
        self.client = httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(600.0, connect=15.0),
        )

    def chat(self, model: str, messages: list, max_tokens: int = 4000,
             json_mode: bool = False) -> str:
        body = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(3):
            try:
                r = self.client.post("/chat/completions", json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"] or ""
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise
                print(f"    retry ({e}) ...")
                time.sleep(3 * (attempt + 1))
        return ""


SYSTEM = "You are a senior Salesforce developer. Answer precisely and concisely."


def answer_without(api: OpenRouter, task: dict) -> str:
    return api.chat(
        BASE_MODEL,
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": task["prompt"]},
        ],
        max_tokens=2000,
    )


def answer_with(api: OpenRouter, task: dict, trace: str, conclusion: str) -> str:
    expert = trace
    if conclusion:
        expert += f"\n\n[Expert conclusion]\n{conclusion}"
    user = (
        f"{task['prompt']}\n\n"
        f"<expert_reasoning>\n{expert}\n</expert_reasoning>\n\n"
        "A stronger reasoning model produced the analysis above. Use it to "
        "inform your answer, but verify it against your own knowledge. Give "
        "your final answer."
    )
    return api.chat(
        BASE_MODEL,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        max_tokens=2000,
    )


JUDGE_TEMPLATE = """You are grading two candidate answers to a Salesforce development question against a reference answer. Be strict and objective.

# Question
{prompt}

# Reference answer (ground truth)
{reference}

# Scoring rubric (each criterion is worth points; judge whether the answer satisfies it)
{rubric}

# Candidate A
{answer_a}

# Candidate B
{answer_b}

Score each candidate from 0 to 10 for how correct and complete it is versus the reference and rubric. Then decide which is better overall.

Respond with ONLY a JSON object:
{{"score_a": <int 0-10>, "score_b": <int 0-10>, "better": "A" | "B" | "tie", "justification": "<two sentences>"}}"""


def judge(api: OpenRouter, task: dict, ans_a: str, ans_b: str) -> dict:
    rubric = "\n".join(f"- {c}" for c in task["rubric"])
    prompt = JUDGE_TEMPLATE.format(
        prompt=task["prompt"], reference=task["reference"], rubric=rubric,
        answer_a=ans_a, answer_b=ans_b,
    )
    # Generous budget: the judge is a reasoning model, so its reasoning tokens
    # plus the JSON verdict must both fit under max_tokens.
    raw = api.chat(JUDGE_MODEL, [{"role": "user", "content": prompt}],
                   max_tokens=8000, json_mode=True)
    return _parse_judge(raw)


def _parse_judge(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    sa = re.search(r"score_a\D+(\d+)", raw)
    sb = re.search(r"score_b\D+(\d+)", raw)
    return {
        "score_a": int(sa.group(1)) if sa else 0,
        "score_b": int(sb.group(1)) if sb else 0,
        "better": "tie",
        "justification": "unparseable judge output; recorded raw scores if any",
    }


def run_task(api: OpenRouter, backend: OpenRouterBackend, task: dict, idx: int) -> dict:
    print(f"  [{task['id']}] WITHOUT ({BASE_LABEL}) ...")
    without = answer_without(api, task)

    print(f"  [{task['id']}] reasoning trace ({REASONING_LABEL}) ...")
    result = backend.reason(task["prompt"])

    print(f"  [{task['id']}] WITH ({BASE_LABEL} + trace) ...")
    with_ = answer_with(api, task, result.trace, result.conclusion)

    # Blind pairwise: alternate which condition is presented as "A" so the
    # judge can't learn a position preference.
    with_is_a = idx % 2 == 0
    ans_a, ans_b = (with_, without) if with_is_a else (without, with_)
    print(f"  [{task['id']}] judging (blind, {JUDGE_MODEL}) ...")
    verdict = judge(api, task, ans_a, ans_b)

    if with_is_a:
        score_with, score_without = verdict.get("score_a", 0), verdict.get("score_b", 0)
        better_raw = verdict.get("better", "tie")
        winner = {"A": "with", "B": "without", "tie": "tie"}.get(better_raw, "tie")
    else:
        score_without, score_with = verdict.get("score_a", 0), verdict.get("score_b", 0)
        better_raw = verdict.get("better", "tie")
        winner = {"A": "without", "B": "with", "tie": "tie"}.get(better_raw, "tie")

    return {
        "id": task["id"],
        "title": task["title"],
        "category": task["category"],
        "answer_without": without,
        "answer_with": with_,
        "reasoning_trace": result.trace,
        "reasoning_conclusion": result.conclusion,
        "score_without": score_without,
        "score_with": score_with,
        "winner": winner,
        "judge_justification": verdict.get("justification", ""),
    }


def write_task_md(rec: dict, task: dict) -> None:
    (RESULTS_DIR / "tasks").mkdir(parents=True, exist_ok=True)
    delta = rec["score_with"] - rec["score_without"]
    md = f"""# {rec['title']}

**Category:** {rec['category']} · **Task ID:** `{rec['id']}`

| Condition | Score (0-10) |
|---|---|
| {BASE_LABEL} alone (WITHOUT) | **{rec['score_without']}** |
| {BASE_LABEL} + Reasoning Traces (WITH) | **{rec['score_with']}** |
| Delta | **{delta:+d}** — judge preferred: **{rec['winner'].upper()}** |

_Judge ({JUDGE_MODEL}, blind pairwise):_ {rec['judge_justification']}

---

## Task

{task['prompt']}

---

## WITHOUT — {BASE_LABEL} alone

{rec['answer_without']}

---

## WITH — {BASE_LABEL} + `deep_reasoning` trace ({REASONING_LABEL})

{rec['answer_with']}

---

<details>
<summary>Reasoning trace supplied to the base model (from {REASONING_LABEL})</summary>

{rec['reasoning_trace'] or '(model returned no separate trace)'}

{('**Conclusion:** ' + rec['reasoning_conclusion']) if rec['reasoning_conclusion'] else ''}

</details>

---

## Reference answer (ground truth)

{task['reference']}
"""
    (RESULTS_DIR / "tasks" / f"{rec['id']}.md").write_text(md)


def write_summary(records: list) -> None:
    n = len(records)
    avg_without = sum(r["score_without"] for r in records) / n
    avg_with = sum(r["score_with"] for r in records) / n
    wins = sum(1 for r in records if r["winner"] == "with")
    ties = sum(1 for r in records if r["winner"] == "tie")
    losses = n - wins - ties

    rows = "\n".join(
        f"| {r['title']} | {r['category']} | {r['score_without']} | "
        f"{r['score_with']} | {r['score_with'] - r['score_without']:+d} | "
        f"{r['winner']} | [details](tasks/{r['id']}.md) |"
        for r in records
    )
    md = f"""# Reasoning Traces — Salesforce demo results

**Base model:** {BASE_LABEL} (`{BASE_MODEL}`) · **Reasoning model:** {REASONING_LABEL} · **Judge:** {JUDGE_MODEL} (blind, pairwise)

## Headline

- Average score **WITHOUT** Reasoning Traces: **{avg_without:.1f}/10**
- Average score **WITH** Reasoning Traces: **{avg_with:.1f}/10**
- Uplift: **{avg_with - avg_without:+.1f} points** ({(avg_with - avg_without) / max(avg_without, 0.01) * 100:+.0f}%)
- Judge preferred WITH in **{wins}/{n}** tasks (ties: {ties}, base won: {losses})

> The premise the customer cares about: a cheap, fast base model ({BASE_LABEL})
> reaches near–frontier quality on hard Salesforce/Apex problems when it can
> escalate to a stronger reasoning model through the `/reason` tool — without
> running the expensive model on every request.

## Per-task scores

| Task | Category | Without | With | Δ | Judge pick | |
|---|---|---|---|---|---|---|
{rows}

## Method

For each task the base model answers twice: once alone, once after receiving the
reasoning trace that Reasoning Traces' `deep_reasoning` tool produces (identical
to the plugin's real behavior). A neutral judge from a different model family
scores both answers blind and pairwise against a fixed reference answer, with the
WITH/WITHOUT presentation order alternated per task to remove position bias.

Model outputs are stochastic, so absolute numbers vary run to run; re-run with
`python examples/run_demo.py`. Raw scores are in `results.json`.
"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "summary.md").write_text(md)


def update_readme_results(records: list) -> None:
    readme = EXAMPLES_DIR / "README.md"
    if not readme.exists():
        return
    n = len(records)
    avg_without = sum(r["score_without"] for r in records) / n
    avg_with = sum(r["score_with"] for r in records) / n
    wins = sum(1 for r in records if r["winner"] == "with")
    rows = "\n".join(
        f"| {r['title']} | {r['score_without']} | {r['score_with']} | "
        f"{r['score_with'] - r['score_without']:+d} |"
        for r in records
    )
    block = f"""<!-- RESULTS:START -->
**Latest run** — base **{BASE_LABEL}**, reasoning **{REASONING_LABEL}**, judge **{JUDGE_MODEL}** (blind):

| | Avg score /10 |
|---|---|
| {BASE_LABEL} alone | **{avg_without:.1f}** |
| {BASE_LABEL} + Reasoning Traces | **{avg_with:.1f}** |

Judge preferred the reasoning-assisted answer in **{wins}/{n}** tasks. Uplift **{avg_with - avg_without:+.1f} points**.

| Task | Without | With | Δ |
|---|---|---|---|
{rows}

Full transcripts: [`results/summary.md`](results/summary.md).
<!-- RESULTS:END -->"""
    text = readme.read_text()
    text = re.sub(r"<!-- RESULTS:START -->.*<!-- RESULTS:END -->", block,
                  text, flags=re.DOTALL)
    readme.write_text(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="run only the first N tasks")
    args = ap.parse_args()

    _load_dotenv()
    api = OpenRouter()
    backend = OpenRouterBackend()  # uses REASONING_MODEL default (Opus 4.8)

    task_files = sorted(TASKS_DIR.glob("*.json"))
    if args.limit:
        task_files = task_files[: args.limit]

    records = []
    for idx, tf in enumerate(task_files):
        task = json.loads(tf.read_text())
        print(f"\n=== Task {idx + 1}/{len(task_files)}: {task['title']} ===")
        rec = run_task(api, backend, task, idx)
        write_task_md(rec, task)
        records.append(rec)
        print(f"  -> without {rec['score_without']} | with {rec['score_with']} "
              f"| winner {rec['winner']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(records, indent=2))
    write_summary(records)
    update_readme_results(records)
    print(f"\nDone. Results in {RESULTS_DIR}")


if __name__ == "__main__":
    main()

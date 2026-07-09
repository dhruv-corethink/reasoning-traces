#!/usr/bin/env python3
"""Coding demo harness — reference-free with/without `/reason` comparison.

Same idea as ../run_demo.py (the Salesforce demo) but for open-ended coding
tasks that have no fixed answer key: the judge grades each answer against the
requirements stated in the task prompt itself, blind and pairwise.

  WITHOUT  — base model (Haiku) answers alone.
  WITH     — base model answers after receiving the reasoning trace from
             Reasoning Traces' deep_reasoning tool.

Requires OPENROUTER_API_KEY (env or the repo's .env).

  python examples/coding/run.py
  python examples/coding/run.py --limit 2
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from reasoning_traces.backends import OpenRouterBackend  # noqa: E402

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE / "tasks"
RESULTS_DIR = HERE / "results"

BASE_MODEL = os.environ.get("BASE_MODEL", "anthropic/claude-haiku-4.5")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "openai/gpt-5")
BASE_LABEL = os.environ.get("BASE_LABEL", "Claude Haiku 4.5")
REASONING_LABEL = os.environ.get("REASONING_LABEL", "Claude Opus 4.8 (via /reason)")


def _load_key() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class OpenRouter:
    def __init__(self) -> None:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            sys.exit("OPENROUTER_API_KEY not set (put it in the repo's .env).")
        self.client = httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(600.0, connect=15.0),
        )

    def chat(self, model, messages, max_tokens=2800, json_mode=False):
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


SYSTEM = "You are a senior software engineer. Produce a complete, correct solution."


def answer_without(api, task):
    return api.chat(BASE_MODEL, [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task["prompt"]},
    ])


def answer_with(api, task, trace, conclusion):
    expert = trace + (f"\n\n[Expert conclusion]\n{conclusion}" if conclusion else "")
    user = (f"{task['prompt']}\n\n<expert_reasoning>\n{expert}\n</expert_reasoning>\n\n"
            "A stronger reasoning model produced the analysis above. Use it to inform "
            "your solution, but verify it. Produce your final solution.")
    return api.chat(BASE_MODEL, [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ])


JUDGE_TEMPLATE = """You are grading two candidate solutions to a software task. There is no reference solution; grade strictly against the requirements stated in the task itself.

# Task
{prompt}

# Requirements the solution must satisfy
{rubric}

# Candidate A
{answer_a}

# Candidate B
{answer_b}

Score each candidate 0-10 for how completely and correctly it satisfies the task's stated requirements. Judge substance, not length. Then pick the better solution.

Respond with ONLY JSON:
{{"score_a": <int 0-10>, "score_b": <int 0-10>, "better": "A"|"B"|"tie", "justification": "<two sentences>"}}"""


def judge(api, task, a, b):
    rubric = "\n".join(f"- {c}" for c in task["rubric"])
    prompt = JUDGE_TEMPLATE.format(prompt=task["prompt"], rubric=rubric, answer_a=a, answer_b=b)
    raw = api.chat(JUDGE_MODEL, [{"role": "user", "content": prompt}],
                   max_tokens=8000, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"score_a": 0, "score_b": 0, "better": "tie", "justification": "unparseable"}


def run_task(api, backend, task, idx):
    print(f"  [{task['id']}] WITHOUT ...")
    without = answer_without(api, task)
    print(f"  [{task['id']}] reasoning trace ...")
    res = backend.reason(task["prompt"])
    print(f"  [{task['id']}] WITH ...")
    with_ = answer_with(api, task, res.trace, res.conclusion)
    with_is_a = idx % 2 == 0
    a, b = (with_, without) if with_is_a else (without, with_)
    print(f"  [{task['id']}] judging ...")
    v = judge(api, task, a, b)
    if with_is_a:
        so, sw = v.get("score_b", 0), v.get("score_a", 0)
        winner = {"A": "with", "B": "without", "tie": "tie"}.get(v.get("better"), "tie")
    else:
        so, sw = v.get("score_a", 0), v.get("score_b", 0)
        winner = {"A": "without", "B": "with", "tie": "tie"}.get(v.get("better"), "tie")
    return {"id": task["id"], "title": task["title"], "category": task["category"],
            "answer_without": without, "answer_with": with_,
            "reasoning_trace": res.trace, "reasoning_conclusion": res.conclusion,
            "score_without": so, "score_with": sw, "winner": winner,
            "judge_justification": v.get("justification", "")}


def write_task_md(rec, task):
    (RESULTS_DIR / "tasks").mkdir(parents=True, exist_ok=True)
    d = rec["score_with"] - rec["score_without"]
    md = f"""# {rec['title']}

**Category:** {rec['category']} · `{rec['id']}`

| Condition | Score /10 |
|---|---|
| {BASE_LABEL} alone | **{rec['score_without']}** |
| {BASE_LABEL} + `/reason` | **{rec['score_with']}** |
| Delta | **{d:+d}** — judge pick: **{rec['winner'].upper()}** |

_Judge ({JUDGE_MODEL}, blind pairwise):_ {rec['judge_justification']}

---

## Task
{task['prompt']}

---

## WITHOUT — {BASE_LABEL} alone
{rec['answer_without']}

---

## WITH — {BASE_LABEL} + `/reason` ({REASONING_LABEL})
{rec['answer_with']}

---

<details><summary>Reasoning trace supplied to the base model</summary>

{rec['reasoning_trace'] or '(no separate trace)'}

{('**Conclusion:** ' + rec['reasoning_conclusion']) if rec['reasoning_conclusion'] else ''}
</details>
"""
    (RESULTS_DIR / "tasks" / f"{rec['id']}.md").write_text(md)


def write_summary(records):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(records, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    _load_key()
    api = OpenRouter()
    backend = OpenRouterBackend()
    files = sorted(TASKS_DIR.glob("*.json"))
    if args.limit:
        files = files[: args.limit]
    records = []
    for idx, tf in enumerate(files):
        task = json.loads(tf.read_text())
        print(f"\n=== {task['category']}: {task['title']} ===")
        rec = run_task(api, backend, task, idx)
        write_task_md(rec, task)
        records.append(rec)
        write_summary(records)
        print(f"  -> without {rec['score_without']} | with {rec['score_with']} | {rec['winner']}")
    print(f"\nDone. {len(records)} tasks -> {RESULTS_DIR}")


if __name__ == "__main__":
    main()

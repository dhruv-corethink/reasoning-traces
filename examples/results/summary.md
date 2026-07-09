# Reasoning Traces — Salesforce demo results

**Base model:** Claude Haiku 4.5 (`anthropic/claude-haiku-4.5`) · **Reasoning model:** Claude Opus 4.8 · **Judge:** openai/gpt-5 (blind, pairwise)

## Headline

- Average score **WITHOUT** Reasoning Traces: **6.0/10**
- Average score **WITH** Reasoning Traces: **8.8/10**
- Uplift: **+2.8 points** (+47%)
- Judge preferred WITH in **3/5** tasks (ties: 1, base won: 1)

> The premise the customer cares about: a cheap, fast base model (Claude Haiku 4.5)
> reaches near–frontier quality on hard Salesforce/Apex problems when it can
> escalate to a stronger reasoning model through the `/reason` tool — without
> running the expensive model on every request.

## Per-task scores

| Task | Category | Without | With | Δ | Judge pick | |
|---|---|---|---|---|---|---|
| Apex trigger: bulkification & governor limits | Apex triggers | 6 | 10 | +4 | with | [details](tasks/01_trigger_bulkification.md) |
| Batch Apex governor-limit math (sync vs async) | Governor limits | 5 | 4 | -1 | without | [details](tasks/02_governor_limits_math.md) |
| SOQL: Accounts with zero Opportunities | SOQL | 7 | 10 | +3 | with | [details](tasks/03_soql_semijoin.md) |
| Batch Apex: wrong running total | Batch Apex | 2 | 10 | +8 | with | [details](tasks/04_batch_stateful.md) |
| CPQ: prorated + discounted add-on | CPQ / pricing math | 10 | 10 | +0 | tie | [details](tasks/05_cpq_proration.md) |

## Method

For each task the base model answers twice: once alone, once after receiving the
reasoning trace that Reasoning Traces' `deep_reasoning` tool produces (identical
to the plugin's real behavior). A neutral judge from a different model family
scores both answers blind and pairwise against a fixed reference answer, with the
WITH/WITHOUT presentation order alternated per task to remove position bias.

Model outputs are stochastic, so absolute numbers vary run to run; re-run with
`python examples/run_demo.py`. Raw scores are in `results.json`.

# Batch Apex: wrong running total

**Category:** Batch Apex · **Task ID:** `04_batch_stateful`

| Condition | Score (0-10) |
|---|---|
| Claude Haiku 4.5 alone (WITHOUT) | **2** |
| Claude Haiku 4.5 + Reasoning Traces (WITH) | **10** |
| Delta | **+8** — judge preferred: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate B correctly identifies the missing Database.Stateful, explains the per-chunk instance reset, and provides the exact fix with code, noting state is preserved into finish(). Candidate A never mentions Database.Stateful and suggests incorrect/irrelevant alternatives (e.g., Database.getSessionState), failing to provide the required exact fix.

---

## Task

This Batch Apex is supposed to sum the Amount of every Opportunity it processes and email the grand total in finish(). Instead it emails a total that is far too small (roughly only the last chunk, or zero). Explain the root cause and give the exact fix.

global class SumOppBatch implements Database.Batchable<sObject> {
    global Decimal grandTotal = 0;
    global Database.QueryLocator start(Database.BatchableContext bc) {
        return Database.getQueryLocator('SELECT Amount FROM Opportunity');
    }
    global void execute(Database.BatchableContext bc, List<Opportunity> scope) {
        for (Opportunity o : scope) grandTotal += (o.Amount == null ? 0 : o.Amount);
    }
    global void finish(Database.BatchableContext bc) {
        // sends an email containing grandTotal
    }
}

---

## WITHOUT — Claude Haiku 4.5 alone

# Root Cause

Batch Apex creates **separate class instances for each batch chunk**. The `grandTotal` instance variable is not shared across batch executions—each chunk gets its own instance with `grandTotal = 0`, so only the last chunk's sum (or zero if it's small) is visible in `finish()`.

# Exact Fix

Use `Database.getSessionState()` to store the total, or better yet, query the sum directly in `finish()`:

```java
global class SumOppBatch implements Database.Batchable<sObject> {
    global Database.QueryLocator start(Database.BatchableContext bc) {
        return Database.getQueryLocator('SELECT Amount FROM Opportunity');
    }
    global void execute(Database.BatchableContext bc, List<Opportunity> scope) {
        // No-op or do other processing
    }
    global void finish(Database.BatchableContext bc) {
        Decimal grandTotal = [SELECT SUM(Amount) total FROM Opportunity][0].get('total');
        // send email with grandTotal
    }
}
```

Alternatively, if you need the sum *during* batch processing, use a **custom object or AsyncApexJob** to track state, but querying in `finish()` is simpler and more reliable.

---

## WITH — Claude Haiku 4.5 + `deep_reasoning` trace (Claude Opus 4.8)

# Root Cause

Batch Apex **does not preserve instance member variable state between `execute()` invocations by default**. Salesforce deserializes a fresh copy of your class for each chunk of records, so changes to `grandTotal` in one `execute()` call are discarded before the next chunk runs. By `finish()`, `grandTotal` only reflects the last chunk (or is reset entirely).

# The Fix

Add `Database.Stateful` to your class declaration:

```apex
global class SumOppBatch implements Database.Batchable<sObject>, Database.Stateful {
    global Decimal grandTotal = 0;
    
    global Database.QueryLocator start(Database.BatchableContext bc) {
        return Database.getQueryLocator('SELECT Amount FROM Opportunity');
    }
    
    global void execute(Database.BatchableContext bc, List<Opportunity> scope) {
        for (Opportunity o : scope) grandTotal += (o.Amount == null ? 0 : o.Amount);
    }
    
    global void finish(Database.BatchableContext bc) {
        // grandTotal now contains the true sum across ALL chunks
    }
}
```

**Only change:** Add `, Database.Stateful` to the `implements` clause.

This tells Salesforce to preserve instance variable values across all `execute()` calls and into `finish()`, giving you the correct grand total.

---

<details>
<summary>Reasoning trace supplied to the base model (from Claude Opus 4.8)</summary>

(model returned no separate trace)

**Conclusion:** # Root Cause: Batch State Is Not Preserved Across Chunks

By default, **Batch Apex does not maintain instance member variable state between `execute()` invocations.** 

Here's what actually happens at runtime:

1. Salesforce serializes your batch instance at the start.
2. For **each chunk** of records, it **deserializes a fresh copy** of the class to run `execute()`.
3. Any changes you made to `grandTotal` in one `execute()` call are **discarded** before the next chunk runs.
4. By `finish()`, `grandTotal` reflects (roughly) only the last chunk — or is effectively reset — which is exactly the symptom you're seeing.

Your accumulation logic is correct; the problem is that the running total is being thrown away between batches.

---

# The Fix: Implement `Database.Stateful`

Add `Database.Stateful` to the class declaration. This tells Salesforce to preserve instance member variable values across all `execute()` calls and into `finish()`.

```apex
global class SumOppBatch implements Database.Batchable<sObject>, Database.Stateful {
    global Decimal grandTotal = 0;

    global Database.QueryLocator start(Database.BatchableContext bc) {
        return Database.getQueryLocator('SELECT Amount FROM Opportunity');
    }

    global void execute(Database.BatchableContext bc, List<Opportunity> scope) {
        for (Opportunity o : scope) {
            grandTotal += (o.Amount == null ? 0 : o.Amount);
        }
    }

    global void finish(Database.BatchableContext bc) {
        // grandTotal now holds the true sum across ALL chunks — send email
    }
}
```

---

# Key Points

- **Only change needed:** add `, Database.Stateful` to the `implements` list.
- With `Database.Stateful`, member variables retain their values across the entire batch execution.
- Note: `Database.Stateful` preserves **instance variables**, not static variables. Static variables still reset per transaction, so keep `grandTotal` as an instance member (as it already is).
- Minor best practice: consider `SELECT Amount FROM Opportunity WHERE Amount != null` to skip null handling, though your ternary already handles it safely.

</details>

---

## Reference answer (ground truth)

Root cause: the class does not implement Database.Stateful. By default, member variable state is NOT preserved across execute() invocations in Batch Apex — Salesforce constructs/deserializes a fresh instance of the batch class for each chunk (and again for finish()), so `grandTotal` resets to 0 at the start of every execute(). The accumulation therefore never carries across chunks, and finish() sees a fresh instance where grandTotal is 0 (or only reflects state that happens not to have been preserved). Fix: implement the Database.Stateful marker interface so instance member variables retain their values across transactions:

global class SumOppBatch implements Database.Batchable<sObject>, Database.Stateful { ... }

With Database.Stateful, grandTotal persists across all execute() calls and finish() sees the correct grand total.

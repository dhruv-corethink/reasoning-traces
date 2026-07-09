# Batch Apex governor-limit math (sync vs async)

**Category:** Governor limits · **Task ID:** `02_governor_limits_math`

| Condition | Score (0-10) |
|---|---|
| Claude Haiku 4.5 alone (WITHOUT) | **5** |
| Claude Haiku 4.5 + Reasoning Traces (WITH) | **4** |
| Delta | **-1** — judge preferred: **WITHOUT** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate A correctly identifies per-execute scoping and the actual failing limit (200 DML > 150), but misstates SOQL math and uses the wrong SOQL limit, and doesn’t address bulkifying the query. Candidate B gets the per-batch math and a fully bulkified fix, but uses the synchronous SOQL limit (100) and wrongly concludes the failure is on SOQL instead of DML, which is a critical error.

---

## Task

A Batch Apex job processes 12,000 Contact records with a batch size of 200. Inside execute(), the code runs exactly 1 SOQL query and 1 DML update per Contact. Will this job hit a governor limit? Show the math, name the specific limit(s) involved with their numeric values, and if it fails, give the fix.

---

## WITHOUT — Claude Haiku 4.5 alone

# Governor Limit Analysis

## The Math

**Batch execution breakdown:**
- 12,000 records ÷ 200 batch size = **60 batches**
- Per batch: 1 SOQL + (200 × 1 DML) = 1 SOQL + 200 DML operations

**Total across all batches:**
- SOQL queries: 60 × 1 = **60 queries** ✅
- DML statements: 60 × 200 = **12,000 DML statements** ❌

## Governor Limits Hit

| Limit | Value | Usage | Status |
|-------|-------|-------|--------|
| SOQL queries per transaction | 100 | 60 | ✅ PASS |
| **DML statements per transaction** | **150** | **12,000** | ❌ **FAIL** |

## The Problem

Each batch execution is a separate transaction with its own governor limit context. **Per batch you execute 200 DML operations (1 update per Contact), but the limit is 150 DML statements per transaction.**

Batches 1-150 will fail when trying to execute the 151st DML statement in a single execute() call.

## The Fix

**Batch all DML into a single update statement:**

```apex
public void execute(Database.BatchableContext bc, List<Contact> contacts) {
    // Process records
    for (Contact c : contacts) {
        c.LastName = c.LastName.toUpperCase(); // example
    }
    
    // Single DML statement for entire batch
    update contacts; // 1 DML, not 200
}
```

This reduces DML per batch to **1 statement**, well under the 150 limit. ✅

---

## WITH — Claude Haiku 4.5 + `deep_reasoning` trace (Claude Opus 4.8)

# Governor Limit Analysis

## The Math

- **Total records:** 12,000
- **Batch size:** 200
- **Batches executed:** 12,000 ÷ 200 = **60 execute() calls**

**Per batch (each execute() transaction):**
- SOQL queries: 1 per Contact × 200 = **200 queries**
- DML statements: 1 per Contact × 200 = **200 statements**

## Limits Hit

| Limit | Per-Transaction Value | Your Usage | Status |
|-------|----------------------|-----------|--------|
| SOQL Queries | **100** | 200 | ❌ **FAIL** |
| DML Statements | **150** | 200 | ❌ **FAIL** |

**Result:** The job **fails on the 101st SOQL query** with:
```
System.LimitException: Too many SOQL queries: 101
```

---

## The Fix: Bulkify the Code

Move SOQL and DML **outside the loop**:

```apex
public void execute(Database.BatchableContext bc, List<Contact> scope) {
    // Collect all IDs needed
    Set<Id> accountIds = new Set<Id>();
    for (Contact c : scope) {
        accountIds.add(c.AccountId);
    }
    
    // 1 SOQL query for entire batch
    Map<Id, Account> accounts = new Map<Id, Account>(
        [SELECT Id, Name FROM Account WHERE Id IN :accountIds]
    );
    
    // Bulk update list
    List<Contact> toUpdate = new List<Contact>();
    for (Contact c : scope) {
        if (accounts.containsKey(c.AccountId)) {
            c.Description = accounts.get(c.AccountId).Name;
            toUpdate.add(c);
        }
    }
    
    // 1 DML statement for entire batch
    update toUpdate;
}
```

**After fix (per batch):**
- SOQL: **1** ✅
- DML: **1** ✅

---

<details>
<summary>Reasoning trace supplied to the base model (from Claude Opus 4.8)</summary>

With a batch size of 200 and 12,000 records, that's 60 separate transactions. Each execute() runs one SOQL query and one DML update per Contact, so 200 of each per batch. Since the SOQL limit is 100 per transaction, I'm hitting the governor limit immediately—200 queries exceeds the 100-query threshold and causes a failure.

The fix is to bulkify the code: collect all the Contacts into a list first, run a single SOQL query to fetch the data I need, then perform one bulk DML update on the entire list. This way I'm using just 1 SOQL query and 1 DML statement per batch instead of 200 of each, staying well within the governor limits.

**Conclusion:** ## The Math

- **Total records:** 12,000
- **Batch size:** 200
- **Number of batches (execute calls):** 12,000 ÷ 200 = **60 execute() invocations**

The critical point: **each execute() runs in its own transaction** with its own fresh set of governor limits. So you don't sum across all 60 — you evaluate the limits **per batch of 200**.

Inside one execute() with 200 Contacts:
- **SOQL queries:** 1 × 200 = **200 queries**
- **DML statements:** 1 × 200 = **200 DML statements**

## The Limits Involved

| Governor Limit | Value (per transaction) | Your usage per batch | Result |
|---|---|---|---|
| Total SOQL queries | **100** | 200 | ❌ **EXCEEDED** |
| Total DML statements | **150** | 200 | ❌ Exceeded |
| Total DML rows | 10,000 | 200 | ✅ OK |

## Verdict: YES, it fails

The **SOQL query limit (100)** is hit **first**. On the **101st SOQL query** inside the loop, Salesforce throws:

```
System.LimitException: Too many SOQL queries: 101
```

(The DML statement limit of 150 would also be blown, but the SOQL exception fires first since the query happens before the DML on the 101st Contact.)

Note: Batch Apex limits are the *synchronous* values here — 100 SOQL / 150 DML. Async doesn't get you a higher query count.

## The Fix: Bulkify (move SOQL and DML out of the loop)

The problem is queries/DML **inside** the per-record loop. Refactor to operate on collections.

**Broken pattern:**
```apex
public void execute(Database.BatchableContext bc, List<Contact> scope) {
    for (Contact c : scope) {
        // 1 SOQL PER contact  -> 200 queries
        Account a = [SELECT Id, Name FROM Account WHERE Id = :c.AccountId];
        c.Description = a.Name;
        update c;   // 1 DML PER contact -> 200 statements
    }
}
```

**Fixed pattern:**
```apex
public void execute(Database.BatchableContext bc, List<Contact> scope) {
    // Collect parent Ids
    Set<Id> acctIds = new Set<Id>();
    for (Contact c : scope) acctIds.add(c.AccountId);

    // 1 SOQL total for the whole batch
    Map<Id, Account> acctMap = new Map<Id, Account>(
        [SELECT Id, Name FROM Account WHERE Id IN :acctIds]
    );

    // Build the update list in memory
    List<Contact> toUpdate = new List<Contact>();
    for (Contact c : scope) {
        if (acctMap.containsKey(c.AccountId)) {
            c.Description = acctMap.get(c.AccountId).Name;
            toUpdate.add(c);
        }
    }

    // 1 DML statement total for the whole batch
    update toUpdate;
}
```

**After the fix (per batch of 200):**
- SOQL queries: **1** (limit 100) ✅
- DML statements: **1** (limit 150) ✅
- DML rows: **200** (limit 10,000) ✅

The job now runs cleanly across all 60 batches.

</details>

---

## Reference answer (ground truth)

Governor limits are enforced PER execute() transaction (one chunk of 200 records), not across the full 12,000 — the total record count is a distractor. Batch Apex runs in ASYNCHRONOUS context, which has different limits than synchronous: SOQL queries limit = 200 (async; sync is 100), DML statements limit = 150 (same in both). Per execute of 200 Contacts: SOQL = 1 × 200 = 200, which exactly equals the async SOQL limit of 200 — it passes but with zero headroom (any additional query would throw 'Too many SOQL queries: 201'). DML = 1 × 200 = 200, which EXCEEDS the 150 DML-statements limit — the job fails with 'Too many DML statements: 151'. Fix: bulkify — accumulate the updated Contacts in a List and issue a single `update` per execute (1 DML instead of 200), and query needed data in bulk before the loop rather than once per record. Key subtlety: the async SOQL limit is 200, not 100.

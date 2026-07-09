# Apex trigger: bulkification & governor limits

**Category:** Apex triggers · **Task ID:** `01_trigger_bulkification`

| Condition | Score (0-10) |
|---|---|
| Claude Haiku 4.5 alone (WITHOUT) | **6** |
| Claude Haiku 4.5 + Reasoning Traces (WITH) | **10** |
| Delta | **+4** — judge preferred: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate A correctly identifies all three bulk-safety failures (SOQL-in-loop, DML-in-loop, and the lost-update bug) and provides a bulk-safe implementation that aggregates and updates once, also guarding against null AccountId/Amount. Candidate B misses the lost-update bug and their corrected code can still fail or compute incorrectly when Opportunity.Amount is null, with some extraneous reasons not tied to the core issue.

---

## Task

Review this Apex trigger. It works in the UI for single records but fails when a data load inserts 200+ Opportunities at once. List every reason it fails on a bulk insert, and provide a corrected version.

trigger OpportunityTrigger on Opportunity (after insert) {
    for (Opportunity opp : Trigger.new) {
        Account acc = [SELECT Id, Total_Opp_Amount__c FROM Account WHERE Id = :opp.AccountId];
        acc.Total_Opp_Amount__c = (acc.Total_Opp_Amount__c == null ? 0 : acc.Total_Opp_Amount__c) + opp.Amount;
        update acc;
    }
}

---

## WITHOUT — Claude Haiku 4.5 alone

# Bulk Insert Failure Reasons

1. **SOQL in Loop** - Executes 200+ queries (Salesforce limit: 100 per transaction)
2. **DML in Loop** - Executes 200+ updates (Salesforce limit: 150 per transaction)
3. **Duplicate Account Updates** - Same Account updated multiple times if multiple Opps link to it
4. **Governor Limit Exception** - Causes entire batch to fail and rollback
5. **No Error Handling** - Fails silently or crashes without feedback

---

# Corrected Version

```apex
trigger OpportunityTrigger on Opportunity (after insert) {
    // Collect unique AccountIds
    Set<Id> accountIds = new Set<Id>();
    for (Opportunity opp : Trigger.new) {
        accountIds.add(opp.AccountId);
    }
    
    // Single query - retrieve all related Accounts
    Map<Id, Account> accountMap = new Map<Id, Account>(
        [SELECT Id, Total_Opp_Amount__c FROM Account WHERE Id IN :accountIds]
    );
    
    // Aggregate Opportunity amounts by AccountId
    Map<Id, Decimal> oppAmountByAccount = new Map<Id, Decimal>();
    for (Opportunity opp : Trigger.new) {
        Decimal currentAmount = oppAmountByAccount.get(opp.AccountId) ?? 0;
        oppAmountByAccount.put(opp.AccountId, currentAmount + opp.Amount);
    }
    
    // Update Account map with aggregated amounts
    List<Account> accountsToUpdate = new List<Account>();
    for (Id accountId : oppAmountByAccount.keySet()) {
        Account acc = accountMap.get(accountId);
        if (acc != null) {
            acc.Total_Opp_Amount__c = (acc.Total_Opp_Amount__c ?? 0) + oppAmountByAccount.get(accountId);
            accountsToUpdate.add(acc);
        }
    }
    
    // Single DML - update all Accounts
    if (!accountsToUpdate.isEmpty()) {
        update accountsToUpdate;
    }
}
```

**Key Improvements:**
- ✅ 1 SOQL query (not 200+)
- ✅ 1 DML statement (not 200+)
- ✅ Handles duplicate Accounts correctly
- ✅ Null-safe operators
- ✅ Efficient Map lookups

---

## WITH — Claude Haiku 4.5 + `deep_reasoning` trace (Claude Opus 4.8)

# Why This Trigger Fails on Bulk Insert

Your trigger has **five critical failures** when processing 200+ records:

### 1. **SOQL Query in Loop** (Governor Limit: 100 queries/transaction)
```apex
for (Opportunity opp : Trigger.new) {
    Account acc = [SELECT Id, Total_Opp_Amount__c FROM Account WHERE Id = :opp.AccountId];
```
200 Opportunities = 200 separate queries → `System.LimitException: Too many SOQL queries: 101`

### 2. **DML Statements in Loop** (Governor Limit: 150 DML/transaction)
```apex
    update acc;  // executes 200 times
```
200 updates exceed the limit immediately.

### 3. **Data Loss on Shared Accounts**
If multiple Opportunities reference the same Account, each iteration re-queries and re-updates independently. Later iterations overwrite earlier ones, corrupting the total.

### 4. **`QueryException` on Null AccountId**
`WHERE Id = :null` returns no rows. Assigning to a single Account variable throws: `List has no rows for assignment to SObject`

### 5. **`NullPointerException` on Null Amount**
No null-check on `opp.Amount` before arithmetic: `+ opp.Amount` fails if Amount is null.

---

# Corrected Version

```apex
trigger OpportunityTrigger on Opportunity (after insert) {
    
    // 1. Aggregate amounts by Account (skip nulls)
    Map<Id, Decimal> amountByAccountId = new Map<Id, Decimal>();
    
    for (Opportunity opp : Trigger.new) {
        if (opp.AccountId == null) continue;
        
        Decimal amt = opp.Amount != null ? opp.Amount : 0;
        Decimal current = amountByAccountId.get(opp.AccountId) != null 
            ? amountByAccountId.get(opp.AccountId) 
            : 0;
        amountByAccountId.put(opp.AccountId, current + amt);
    }
    
    if (amountByAccountId.isEmpty()) return;
    
    // 2. ONE query for all Accounts
    Map<Id, Account> accounts = new Map<Id, Account>(
        [SELECT Id, Total_Opp_Amount__c 
         FROM Account 
         WHERE Id IN :amountByAccountId.keySet()]
    );
    
    // 3. Update each Account once
    for (Id accId : amountByAccountId.keySet()) {
        Account acc = accounts.get(accId);
        if (acc != null) {
            Decimal current = acc.Total_Opp_Amount__c != null 
                ? acc.Total_Opp_Amount__c 
                : 0;
            acc.Total_Opp_Amount__c = current + amountByAccountId.get(accId);
        }
    }
    
    // 4. ONE DML for all Accounts
    update accounts.values();
}
```

**Key improvements:**
- ✅ Single SOQL query using `IN` clause
- ✅ Single DML update
- ✅ Aggregates amounts per Account before querying
- ✅ Handles null `AccountId` and `Amount`
- ✅ Handles deleted/missing Accounts gracefully

---

<details>
<summary>Reasoning trace supplied to the base model (from Claude Opus 4.8)</summary>

I'm spotting the performance issues in this trigger. The main problems are querying the database inside a loop, which quickly hits Salesforce's governor limits—200 opportunities means 200 separate queries when it should be one batch query. Similarly, updating records in a loop violates the DML statement limit. There's also a data consistency issue where multiple opportunities tied to the same account can cause lost updates if the account gets queried and modified multiple times in sequence.

I also need to handle edge cases: null AccountIds will throw an exception when assigning a query result to a single Account variable, and null Amount values will cause arithmetic errors. The real fix is to aggregate all amounts by account first, then do a single batch query and update operation.

**Conclusion:** # Why This Trigger Fails on Bulk Insert

Your trigger works for one record but breaks the moment a data load pushes 200+ rows through in a single transaction. Here's every reason:

### 1. SOQL query inside a loop (the fatal one)
```apex
for (Opportunity opp : Trigger.new) {
    Account acc = [SELECT ... WHERE Id = :opp.AccountId];  // 1 query PER record
```
Salesforce allows **100 SOQL queries per transaction**. With 200 Opportunities you fire 200 queries → `System.LimitException: Too many SOQL queries: 101`.

### 2. DML statement inside a loop
```apex
    update acc;  // 1 DML PER record
```
The limit is **150 DML statements per transaction**. 200 updates blows this limit too.

### 3. No aggregation — data corruption for shared accounts
If several Opportunities in the batch belong to the **same Account**, each iteration re-queries and re-updates that Account independently. This is redundant, and depending on ordering can produce lost/incorrect totals. You need to sum amounts **per Account** and update each Account once.

### 4. `QueryException` when `AccountId` is null
`WHERE Id = :null` returns zero rows. Assigning zero rows to a single `Account` variable throws **`List has no rows for assignment to SObject`**. Bulk loads frequently include Opportunities without an Account.

### 5. `NullPointerException` on null `Amount`
Your ternary guards `Total_Opp_Amount__c` but **not** `opp.Amount`. If any Opportunity has a null Amount, `... + opp.Amount` throws a `NullPointerException`.

---

# Corrected Version

The fix follows the standard bulkification pattern: **collect → query once → update once**.

```apex
trigger OpportunityTrigger on Opportunity (after insert) {

    // 1. Aggregate the amount to add per Account (skip null AccountIds)
    Map<Id, Decimal> amountByAccountId = new Map<Id, Decimal>();

    for (Opportunity opp : Trigger.new) {
        if (opp.AccountId == null) {
            continue;                          // handles null AccountId
        }
        Decimal amt = (opp.Amount == null) ? 0 : opp.Amount;  // handles null Amount

        Decimal running = amountByAccountId.containsKey(opp.AccountId)
            ? amountByAccountId.get(opp.AccountId)
            : 0;
        amountByAccountId.put(opp.AccountId, running + amt);
    }

    if (amountByAccountId.isEmpty()) {
        return;
    }

    // 2. ONE SOQL query for all related Accounts
    Map<Id, Account> accountsToUpdate = new Map<Id, Account>(
        [SELECT Id, Total_Opp_Amount__c
         FROM Account
         WHERE Id IN :amountByAccountId.keySet()]
    );

    // 3. Apply the aggregated totals
    for (Id accId : amountByAccountId.keySet()) {
        Account acc = accountsToUpdate.get(accId);
        if (acc == null) {
            continue;                          // account may have been deleted
        }
        Decimal current = (acc.Total_Opp_Amount__c == null) ? 0 : acc.Total_Opp_Amount__c;
        acc.Total_Opp_Amount__c = current + amountByAccountId.get(accId);
    }

    // 4. ONE DML statement for all Accounts
    update accountsToUpdate.values();
}
```

## What changed

| Problem | Fix |
|---|---|
| SOQL in loop | Single query using `WHERE Id IN :keySet()` |
| DML in loop | Single `update` on a collection |
| No aggregation | `Map<Id, Decimal>` sums amounts per Account |
| Null `AccountId` | `continue` skips them |
| Null `Amount` | Coalesced to `0` |
| Missing Account record | Null-check after the map lookup |

## Recommendations beyond the immediate fix

- **Move logic into a handler class.** Triggers should delegate to an Apex class (e.g., `OpportunityTriggerHandler`) rather than holding business logic. This keeps it testable and maintainable.
- **Consider a rollup solution instead.** If `Total_Opp_Amount__c` is a straight sum of Opportunity Amounts, a **Roll-Up Summary field** (if the relationship is master-detail) or a declarative rollup tool handles this without code and correctly manages updates *and* deletes/reparenting. This trigger only handles `after insert` — it won't recalculate on update, delete, or undelete.
- **Write a bulk test** that inserts 200+ Opportunities (including some sharing an Account, some with null Amount, and one with null AccountId) to lock in the behavior.

</details>

---

## Reference answer (ground truth)

Three bulk-safety failures: (1) SOQL query inside the for loop — 200 opps issues 200 queries and hits the 100-SOQL-queries-per-transaction limit at the 101st. (2) DML (update) inside the loop — hits the 150-DML-statements-per-transaction limit. (3) No aggregation across records for the same Account: if several opps in the batch share an AccountId, each iteration re-queries the pre-loop value and overwrites, so all but the last increment are lost (lost-update bug). Correct approach: collect AccountIds from Trigger.new, query the matching Accounts once into a Map<Id,Account>, accumulate each opp's Amount onto the in-memory Account in the map, then issue a single update on the map's values. Example:

trigger OpportunityTrigger on Opportunity (after insert) {
    Set<Id> acctIds = new Set<Id>();
    for (Opportunity o : Trigger.new) if (o.AccountId != null) acctIds.add(o.AccountId);
    Map<Id, Account> accts = new Map<Id, Account>([SELECT Id, Total_Opp_Amount__c FROM Account WHERE Id IN :acctIds]);
    for (Opportunity o : Trigger.new) {
        if (o.AccountId == null) continue;
        Account a = accts.get(o.AccountId);
        a.Total_Opp_Amount__c = (a.Total_Opp_Amount__c == null ? 0 : a.Total_Opp_Amount__c) + (o.Amount == null ? 0 : o.Amount);
    }
    update accts.values();
}

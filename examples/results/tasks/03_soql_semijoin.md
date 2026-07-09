# SOQL: Accounts with zero Opportunities

**Category:** SOQL · **Task ID:** `03_soql_semijoin`

| Condition | Score (0-10) |
|---|---|
| Claude Haiku 4.5 alone (WITHOUT) | **7** |
| Claude Haiku 4.5 + Reasoning Traces (WITH) | **10** |
| Delta | **+3** — judge preferred: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate A provides the correct semi-join query and accurately explains why both the child subquery and SQL-style JOIN approaches fail in SOQL. Candidate B gives the right query and notes the child subquery issue, but incorrectly claims a LEFT OUTER JOIN is syntactically valid in SOQL, which undermines the explanation.

---

## Task

Write a SINGLE SOQL query that returns only the Accounts that have no related Opportunity records (zero child Opportunities). Explain why the common first attempts (a child relationship subquery, or a JOIN) do not directly satisfy 'a single query that returns only the childless Accounts'.

---

## WITHOUT — Claude Haiku 4.5 alone

# SOQL Query for Accounts with No Opportunities

```soql
SELECT Id, Name FROM Account WHERE Id NOT IN (SELECT AccountId FROM Opportunity)
```

## Why Common Approaches Fail

**1. Child Relationship Subquery (Common Mistake)**
```soql
SELECT Id, Name, (SELECT Id FROM Opportunities) FROM Account
```
❌ **Problem**: This returns *all* Accounts—even those with zero Opportunities. The subquery result is simply empty for childless records, but the parent Account is still returned.

**2. LEFT OUTER JOIN (Common Mistake)**
```soql
SELECT Account.Id, Account.Name FROM Account 
LEFT OUTER JOIN Opportunity ON Account.Id = Opportunity.AccountId 
WHERE Opportunity.Id = NULL
```
❌ **Problem**: While syntactically valid, this approach is inefficient and still requires filtering. More importantly, it's unnecessarily complex for this use case and can cause unexpected behavior with large datasets.

## Why the NOT IN Subquery Works

The `NOT IN` query with a subquery directly filters at the query level:
- The inner query collects all `AccountId` values that *have* related Opportunities
- The outer query **excludes** any Account in that list
- Result: **only Accounts with zero child records**

This is the canonical single-query solution for "find parent records with no children."

---

## WITH — Claude Haiku 4.5 + `deep_reasoning` trace (Claude Opus 4.8)

# SOQL Query for Childless Accounts

## The Working Query

```sql
SELECT Id, Name
FROM Account
WHERE Id NOT IN (SELECT AccountId FROM Opportunity)
```

This anti-join pattern excludes any Account whose Id appears in the Opportunity table, leaving only Accounts with zero related Opportunities.

---

## Why Common First Attempts Fail

### ❌ Attempt 1: Child Relationship Subquery
```sql
SELECT Id, Name, (SELECT Id FROM Opportunities)
FROM Account
```

**Problem:** This returns **all** Accounts—it's a projection, not a filter. The child subquery adds data to each row (empty or populated), but doesn't restrict which Accounts appear. You'd still need Apex code to discard Accounts with populated child lists. The query itself doesn't return "only childless" Accounts.

### ❌ Attempt 2: SQL-Style JOIN
```sql
-- Invalid SOQL
SELECT a.Id FROM Account a
LEFT JOIN Opportunity o ON o.AccountId = a.Id
WHERE o.Id = null
```

**Problem:** SOQL has **no explicit JOIN syntax**. Relationships are traversed only via:
- Parent-to-child subqueries (child relationships)
- Dot-notation for child-to-parent lookups

The classic SQL anti-join idiom doesn't translate directly.

---

## Why `NOT IN` Works

The **anti-join with `NOT IN`** is the idiomatic SOQL solution because it:
- ✅ Operates in the `WHERE` clause (actual filtering, not projection)
- ✅ Uses supported SOQL relationship syntax (inner query on `Opportunity.AccountId`)
- ✅ Returns only matching rows in a single query with no post-processing

---

<details>
<summary>Reasoning trace supplied to the base model (from Claude Opus 4.8)</summary>

(model returned no separate trace)

**Conclusion:** # SOQL Query for Childless Accounts

## The Working Query

```sql
SELECT Id, Name
FROM Account
WHERE Id NOT IN (SELECT AccountId FROM Opportunity)
```

This uses a **semi-join / anti-join** pattern. The inner query returns all `AccountId` values that *do* have Opportunities, and `NOT IN` excludes those, leaving only Accounts with zero child Opportunities.

---

## Why the Common First Attempts Fail

### Attempt 1: Child Relationship Subquery

```sql
SELECT Id, Name, (SELECT Id FROM Opportunities)
FROM Account
```

**Why it doesn't satisfy the requirement:**

- This returns **every** Account, not just childless ones. The subquery is a *projection* (it adds child data to each row), not a *filter*.
- You **cannot filter on aggregate results of a child subquery** in the outer `WHERE`. SOQL does not allow something like `WHERE (SELECT COUNT() FROM Opportunities) = 0`.
- The result includes Accounts *with* Opportunities (they simply have a populated child list) and Accounts *without* them (empty child list). You'd have to loop in Apex afterward to discard the ones that have children — meaning the **query alone** did not return "only the childless Accounts." It shifted the work to code.

### Attempt 2: A SQL-Style JOIN

```sql
-- This is NOT valid SOQL
SELECT a.Id
FROM Account a
LEFT JOIN Opportunity o ON o.AccountId = a.Id
WHERE o.Id = null
```

**Why it doesn't work:**

- **SOQL has no explicit JOIN syntax.** You cannot write `LEFT JOIN ... ON ...` at all — this simply won't compile.
- SOQL relationships are traversed only via **parent-to-child subqueries** or **dot-notation for child-to-parent**, not via arbitrary joins.
- The classic SQL "LEFT JOIN + WHERE child IS NULL" anti-join idiom therefore has no direct SOQL equivalent expressed as a join.

---

## Why the Semi-Join Approach Is the Right Fit

| Aspect | Explanation |
|--------|-------------|
| **Single query** | One statement, no Apex post-processing needed. |
| **Filters, not projects** | `NOT IN` operates in the `WHERE` clause, so it actually *removes* rows rather than annotating them. |
| **Legal SOQL** | Inner-query relationships (semi-join/anti-join) are explicitly supported. |

### Key Constraints to Remember

- The inner query's **selected field must be a relationship/ID field** compatible with the outer field (`Account.Id` ↔ `Opportunity.AccountId`).
- You may only have **one level** of semi-join, and there are limits on how many you can nest.
- `AccountId` on Opportunity is technically nullable is not a concern here — `NOT IN` correctly excludes the set of accounts that appear as parents.

---

## Summary

The requirement—"a **single query** returning **only** childless Accounts"—demands a **filter** on the absence of children. The child subquery only *adds* data (requiring Apex to finish the job), and true JOINs don't exist in SOQL. The **anti-join with `NOT IN`** is the idiomatic SOQL construction that satisfies both conditions natively.

</details>

---

## Reference answer (ground truth)

Use a NOT IN semi-join against the child object's lookup field:

SELECT Id, Name FROM Account WHERE Id NOT IN (SELECT AccountId FROM Opportunity)

Why the common attempts fail: (1) SOQL has no SQL-style JOIN, so you cannot LEFT JOIN and filter on a null child. (2) A child relationship subquery — SELECT Id, (SELECT Id FROM Opportunities) FROM Account — returns ALL accounts (each with its list of child opps), so it does not filter to only childless ones; you'd have to inspect the child list in Apex afterward, which is not a single query that returns only the answer. (3) You cannot filter directly on a child aggregate/count in the WHERE of the parent query. The NOT IN semi-join is the correct single-query solution. (Opportunities with a null AccountId simply aren't in the subquery set and don't affect correctness.)

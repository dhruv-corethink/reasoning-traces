# CPQ: prorated + discounted add-on

**Category:** CPQ / pricing math · **Task ID:** `05_cpq_proration`

| Condition | Score (0-10) |
|---|---|
| Claude Haiku 4.5 alone (WITHOUT) | **10** |
| Claude Haiku 4.5 + Reasoning Traces (WITH) | **10** |
| Delta | **+0** — judge preferred: **TIE** |

_Judge (openai/gpt-5, blind pairwise):_ Both answers correctly compute $510.00, applying the 73/365 proration to the $3,000 add-on and the 15% discount, and they ignore the $12,000 distractor. They show clear steps; A uses the proration factor directly, while B uses a daily-rate approach—both are equivalent.

---

## Task

A customer has an existing annual subscription with a list price of $12,000/year. Mid-term, they add a co-terminated add-on product so it expires with the main subscription. There are 73 days remaining in the 365-day annual term. The add-on's list price is $3,000/year, and a 15% discount applies to the add-on. What is the prorated, discounted amount to charge now for the add-on? Show each step and round to the nearest cent.

---

## WITHOUT — Claude Haiku 4.5 alone

# Prorated Add-On Calculation

## Step 1: Calculate the discounted annual price of the add-on
List price: $3,000
Discount: 15%
Discounted price = $3,000 × (1 - 0.15) = $3,000 × 0.85 = **$2,550/year**

## Step 2: Calculate the daily rate
Daily rate = $2,550 ÷ 365 days = **$6.986301.../day**

## Step 3: Calculate the prorated amount for remaining days
Remaining days: 73
Prorated amount = $6.986301... × 73 = $510.00

## Answer
**$510.00**

The customer should be charged **$510.00** for the co-terminated add-on.

---

## WITH — Claude Haiku 4.5 + `deep_reasoning` trace (Claude Opus 4.8)

# Prorated Add-On Charge Calculation

## Step 1: Apply the 15% discount to the annual list price
$$\$3,000 \times (1 - 0.15) = \$3,000 \times 0.85 = \$2,550.00$$

## Step 2: Calculate the proration factor
Since 73 days remain in the 365-day term:
$$\frac{73}{365} = 0.20$$

## Step 3: Calculate the prorated, discounted charge
$$\$2,550.00 \times 0.20 = \$510.00$$

---

## Final Answer
**$510.00**

The add-on is charged only for the 73 remaining days of the co-terminated subscription at the discounted rate.

---

<details>
<summary>Reasoning trace supplied to the base model (from Claude Opus 4.8)</summary>

The add-on costs $3,000 annually with a 15% discount, bringing it to $2,550. For the 73-day period, that's roughly 20% of the year, so the prorated charge comes to $510.

**Conclusion:** # Prorated Add-On Charge Calculation

## Step 1: Apply the discount to the add-on's annual list price
$$\$3,000 \times (1 - 0.15) = \$3,000 \times 0.85 = \$2,550.00$$

## Step 2: Determine the proration factor
The add-on is co-terminated, so it only covers the **73 days remaining** in the 365-day term:
$$\frac{73}{365} = 0.20$$

## Step 3: Apply the proration factor to the discounted annual price
$$\$2,550.00 \times 0.20 = \$510.00$$

## Result
**Amount to charge now: $510.00**

---

### Summary Table
| Step | Calculation | Result |
|------|-------------|--------|
| Discounted annual price | $3,000 × 0.85 | $2,550.00 |
| Proration factor | 73 ÷ 365 | 0.20 |
| Prorated + discounted charge | $2,550.00 × 0.20 | **$510.00** |

*Note: The existing $12,000/year subscription is not billed again here—it's only referenced to establish the co-termination date (73 days remaining).*

</details>

---

## Reference answer (ground truth)

The $12,000 main-subscription price is a distractor — it does not enter the add-on charge. Steps: (1) Proration factor = days remaining / term days = 73 / 365 = 0.2. (2) Prorated add-on list = $3,000 × 0.2 = $600.00. (3) Apply 15% discount = $600.00 × (1 − 0.15) = $600.00 × 0.85 = $510.00. Answer: $510.00. (Proration and discount are both multiplicative, so order doesn't matter: 3000 × 0.2 × 0.85 = 510.) Common errors to avoid: using a 360-day year, involving the $12,000, or applying the discount to the full $3,000 before prorating in a way that changes the result.

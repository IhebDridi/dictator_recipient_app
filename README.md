# Recipient App — Bonus Allocation Viewer (Production Version)

## Overview

This oTree app implements the **recipient side** of a two‑stage experimental setup.  
Recipients are **passive participants**: they do not make any decisions. Instead, they receive bonus payments that are determined by allocation decisions made earlier by multiple allocators.

Each recipient receives a **set of 100 allocation outcomes**, drawn from a pool of allocator decisions, and their total bonus is calculated as the **sum of all received allocations**.

The app is designed for **production use**, supports **concurrent participants**, and guarantees **no reuse of allocation rounds**.

---

## Role of the Recipient

- Recipients do **not** make any strategic or allocation decisions.
- They receive allocations determined by **many different allocators**.
- Each allocation shown comes from a **different allocator**.
- Allocations are presented round‑by‑round for transparency.
- The recipient’s total bonus is the **sum of all allocations received across rounds**.

---

## Data Source

Allocator decisions are imported from a **preprocessed CSV** into the database table:

```
dictator_csv_minimal
```

Each row corresponds to **one allocator**, with up to **30 allocation rounds**:

```
allocation_round1 … allocation_round30
```

Additionally, each allocator has a column:

```
random_payoff_part ∈ {1, 2, 3}
```

This determines which subset of rounds is usable for payoffs.

---

## Usable Rounds per Allocator

Each allocator contributes **exactly 10 usable rounds**, determined as follows:

- `random_payoff_part = 1` → rounds **1–10**
- `random_payoff_part = 2` → rounds **11–20**
- `random_payoff_part = 3` → rounds **21–30**

All other rounds are ignored entirely.

---

## Allocation Assignment Logic

Allocation assignment is handled by:

```
assign_allocations_from_dictator_csv_minimal(recipient_prolific_id, x=100)
```

### Logic summary

- Runs **once per recipient** (idempotent).
- Uses only **usable rounds** based on `random_payoff_part`.
- Randomly selects **100 distinct allocator–round pairs**.
- **No reuse is allowed**:
  - A dictator–round pair is never assigned to more than one recipient.
- Assignments are written to:

```
recipient_allocations
```

### Capacity constraint

- Number of allocators: **805**
- Usable rounds per allocator: **10**
- Total usable rounds: **8050**
- Rounds per recipient: **100**

**Exactly 80 recipients** can be fully assigned.

For production runs, the session size **must be set to 80**.

---

## Stored Recipient Data

For each recipient, `recipient_allocations` stores:

- `recipient_prolific_id`
- `dictator_prolific_id`
- `round_number`
- `allocated_value` (ECoins received by the recipient)

This guarantees:

- Assignments are persistent.
- Page refreshes do not re‑randomize outcomes.
- Results and final summaries always match stored data.

---

## Bonus Calculation

- Each round starts with **100 ECoins**.
- The allocator keeps some amount; the remainder is received by the recipient.
- Recipient payoff per round is stored directly as `allocated_value`.

### Total bonus

```
total_received = sum of allocated_value over all rounds
```

Conversion:

- **10 ECoins = 1 cent**
- **100 cents = 1 euro**

The Results page displays both ECoins and the converted monetary amount.

---

## Pages and Flow

1. **Informed Consent**
   - Recipient enters Prolific ID.
   - Stored as `participant.label`.

2. **Instructions**
   - Explains the passive receiver role.

3. **Comprehension Test**
   - Recipients must pass to proceed.
   - Three attempts allowed.
   - Failed attempts show which questions were wrong and remaining attempts.
   - Participants who fail three times are excluded.

4. **Results**
   - Allocation assignment occurs here.
   - Displays a table with:
     - Round
     - Allocated (to you)
     - Kept (by allocator)
   - Shows total bonus.

5. **AI Detection Page (conditional)**
   - Shown **only** if the Prolific ID equals:
     ```
     GeAI12345678900987654321
     ```
   - Redirects to a dedicated Prolific completion link.

6. **Thank You / Prolific Redirect**
   - Standard completion page for all other participants.

---

## Concurrency and Safety Guarantees

This app is safe for **simultaneous participants**, provided the following are in place:

- PostgreSQL unique constraint:
  ```
  UNIQUE (dictator_prolific_id, round_number)
  ```
- Retry logic on insert conflicts.
- Explicit handling of stale database connections using:
  ```
  close_old_connections()
  connection.ensure_connection()
  ```
- `sslmode=require` enforced in `DATABASE_URL`.

These guarantees ensure:
- No double assignment of rounds.
- No race conditions under concurrent access.
- Stable operation on Clever Cloud.

---

## Production Configuration

- `OTREE_PRODUCTION=1`
- Gunicorn used as WSGI server:
  ```
  gunicorn otree.wsgi:application
  ```
- PostgreSQL with SSL enforced.
- Session size set manually to **80 participants**.

---

## Relationship to Allocator App

- This app must be run **after** allocator data has been generated and imported.
- Allocator data is **never modified**.
- The recipient app is strictly read‑only with respect to allocator decisions.

---

## Intended Use

This app is intended to:

- Inform recipients about their bonus outcomes.
- Guarantee transparent and reproducible payoff calculations.
- Support large‑scale online experiments with passive payoff recipients.
- Operate reliably under real‑world, concurrent participant traffic.

---

If you want, I can also:
- generate a **data‑flow diagram**
- add a **technical appendix** for reviewers
- or write a **short participant‑facing description** for Prolific
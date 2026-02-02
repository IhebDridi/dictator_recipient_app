# Recipient App — Bonus Allocation Viewer

## Overview

This oTree app implements the **recipient side** of a two‑app experimental setup.  
Recipients do **not make strategic decisions**. Instead, they are informed about their bonus payments, which are determined by allocation decisions made by allocators in a separate app.

The app retrieves allocation data from the allocator database, assigns one allocator and one experimental part to each recipient, and displays the resulting bonus.

---

## Role of the Recipient

- Recipients do not make allocation decisions.
- Their bonus depends on decisions made by **one randomly selected allocator**.
- Only **one part** of the allocator’s experiment is used to determine the recipient’s bonus.
- The same allocator and part are used consistently throughout the app.

---

## Data Source

This app reads allocation data from the allocator app’s database table:

```
dictator_game_player
```

Relevant fields used:
- `prolific_id` (allocator identifier)
- `round_number`
- `allocation` (amount kept by allocator, 0–100)

Recipient payoffs are calculated as:

```
recipient received = 100 − allocation
```

---

## Allocation Assignment Logic

The assignment is handled by the function:

```
assign_allocations_if_needed(recipient_prolific_id)
```

### Logic summary

- Runs once per recipient (idempotent).
- Randomly selects **one valid (allocator, part) pair** that exists in the data.
- Part definitions:
  - Part 1 → rounds 1–10
  - Part 2 → rounds 11–20
  - Part 3 → rounds 21–30
- All available rounds for that allocator and part are selected.
- For each round:
  - Allocator kept amount is read from the database.
  - Recipient received amount is computed as `100 − allocation`.
- Results are written to the table:

```
recipient_allocations
```

---

## Stored Recipient Data

For each recipient, the following information is stored in `recipient_allocations`:

- `recipient_prolific_id`
- `dictator_prolific_id`
- `round_number`
- `part`
- `allocated_value` (amount received by the recipient)

This ensures that:
- Results and Debriefing always match.
- The chosen allocator and part never change.
- Refreshing pages does not re‑randomize outcomes.

---

## Pages and Flow

1. **Informed Consent**
   - Recipient enters Prolific ID.
   - Prolific ID is stored as `participant.label`.

2. **Instructions**

3. **Comprehension Test**
   - Recipients must pass to proceed.
   - Failed participants are excluded.

4. **Results**
   - Displays per‑round allocation outcomes.
   - Shows how much the allocator kept and how much the recipient received.
   - Displays the selected part and total received so far.

5. **Debriefing**
   - Reuses the same data from `recipient_allocations`.
   - Displays final bonus summary.
   - No re‑randomization occurs.

6. **Thank You / Prolific Redirect**

---

## Consistency Guarantees

- Allocator selection happens **once** per recipient.
- Part selection happens **once** per recipient.
- Results and Debriefing always show identical data.
- All displayed values correspond exactly to what is stored in the database.

---

## Development Notes

- The app is robust to incomplete allocator data.
- It does not require allocators to have completed all rounds.
- For production use, allocator data quality should be checked in advance.
- No allocator‑side variables (e.g. `random_payoff_part`) are used here.

---

## Dependencies

- PostgreSQL (recommended)
- oTree
- Django database access via `django.db.connection`

---

## Relationship to Allocator App

- This app must be run **after** the allocator app has generated data.
- It assumes the allocator app stores allocations in `dictator_game_player`.
- The recipient app never modifies allocator data.

---

## Intended Use

This app is intended to:
- Inform recipients about their bonus payments.
- Ensure transparent and consistent payoff computation.
- Support experiments where recipients are passive payoff receivers.

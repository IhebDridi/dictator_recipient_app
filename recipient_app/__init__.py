import os
import django
from django.conf import settings

# Temporary safety net to ensure Django settings are loaded
if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    django.setup()

from otree.api import *
from django.db import connection
import random


# --------------------------------------------------
# oTree constants: single interaction, no grouping
# --------------------------------------------------
class C(BaseConstants):
    NAME_IN_URL = 'recipient'
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = 1
    EXCLUDE_DICTATOR_KEEPS_ZERO = False  #  SWITCH for allocation = 0


class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass


# --------------------------------------------------
# Player model (recipient only)
# --------------------------------------------------
class Player(BasePlayer):
    delete_recipient_id = models.StringField(blank=True) # to delete recipient info in deubg mode
    view_recipient_id = models.StringField(blank=True)  # to view recipient info in deubg mode

    prolific_id = models.StringField(blank=False, label="Please enter your Prolific ID")

    q1 = models.StringField(choices=['a', 'b', 'c', 'd'])
    q2 = models.StringField(choices=['a', 'b', 'c', 'd'])
    q3 = models.StringField(choices=['a', 'b', 'c', 'd'])


    comprehension_attempts = models.IntegerField(initial=0)
    is_excluded = models.BooleanField(initial=False)


# --------------------------------------------------
# INFORMED CONSENT
# --------------------------------------------------
class InformedConsent(Page):
    form_model = 'player'
    form_fields = ['prolific_id']

    def before_next_page(self, timeout_happened=False):
        pid = self.prolific_id.strip()
        self.participant.label = pid  # display only

        # STEP 1: check if this Prolific ID already has allocations
        already_assigned = recipient_has_allocations(pid)
        self.participant.vars['already_assigned'] = already_assigned

        # If YES → do nothing else
        if already_assigned:
            self.participant.vars['exhausted'] = False
            return





# --------------------------------------------------
# INSTRUCTIONS
# --------------------------------------------------
class Instructions(Page):
    def is_displayed(self):
        return self.round_number == 1


# --------------------------------------------------
# COMPREHENSION TEST
# --------------------------------------------------
class ComprehensionTest(Page):
    form_model = 'player'
    form_fields = ['q1', 'q2', 'q3']

    def error_message(self, values):
        correct_answers = {
            'q1': 'b',
            'q2': 'c',
            'q3': 'b',
        }

        # which questions are wrong
        wrong = [
            q for q, correct in correct_answers.items()
            if values.get(q) != correct
        ]

        if wrong:
            self.player.comprehension_attempts += 1

            remaining = 3 - self.player.comprehension_attempts

            # exclude after 3 failed attempts
            if remaining <= 0:
                self.player.is_excluded = True
                return None

            # ✅ only show message AFTER first failed attempt
            return (
                f"You failed questions {', '.join(wrong)}. "
                f"You now only have {remaining} more attempts."
            )


# --------------------------------------------------
# FAILED TEST
# --------------------------------------------------
class FailedTest(Page):
    def is_displayed(self):
        return self.field_maybe_none('is_excluded')
class AIdetectionpage(Page):

    def is_displayed(self):
        return self.participant.label == "GeAI12345678900987654321"


# --------------------------------------------------
# RESULTS
# --------------------------------------------------

class Results(Page):

    def is_displayed(self):
        return self.round_number == 1 and not self.is_excluded

    def vars_for_template(self):
        recipient_key = self.participant.label

        # ✅ ASSIGN HERE (not in before_next_page)
        success = assign_allocations_from_dictator_csv_minimal(
            recipient_prolific_id=recipient_key,
            x=100,
        )
        self.participant.vars['exhausted'] = (success is False)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    round_number,
                    allocated_value
                FROM recipient_allocations
                WHERE recipient_prolific_id = %s
                ORDER BY round_number
                """,
                [recipient_key]
            )
            rows_raw = cursor.fetchall()

        rows = [
            {
                "round": i + 1,
                "received": received,
                "kept": 100 - received,
            }
            for i, (round_n, received) in enumerate(rows_raw)
        ]

        total_received = sum(r["received"] for r in rows)

        return {
            "rows": rows,
            "n_rounds": len(rows),
            "total_received": total_received,
            "total_cents": total_received / 10,
            "recipient_prolific_id": recipient_key,
        }

# --------------------------------------------------
# DEBRIEFING
# --------------------------------------------------
class Debriefing(Page):

    def is_displayed(self):
        return self.round_number == 1

    def vars_for_template(self):
        recipient_key = self.participant.label  # 🔧 FIX (was label)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    round_number,
                    allocated_value,
                    part,
                    dictator_prolific_id
                FROM recipient_allocations
                WHERE recipient_prolific_id = %s
                ORDER BY round_number
                """,
                [recipient_key]
            )
            rows_raw = cursor.fetchall()

        if not rows_raw:
            raise RuntimeError("Debriefing: no recipient_allocations found.")

        rows = [
            {"round": r, "allocated": 100 - received, "received": received}
            for r, received, _, _ in rows_raw
        ]

        return {
            "rows": rows,
            "total_received": sum(r["received"] for r in rows),
        }


# --------------------------------------------------
# THANK YOU
# --------------------------------------------------
class ThankYou(Page):
    def is_displayed(self):
        return self.round_number == 1

class Exhausted(Page):
    def is_displayed(self):
        return self.participant.vars.get('exhausted', False)

class AllocationOverview(Page):
    form_model = 'player'
    form_fields = ['delete_recipient_id', 'view_recipient_id']

    def is_displayed(self):
        return self.round_number == 1

    def vars_for_template(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    recipient_prolific_id,
                    COUNT(*) AS n_rounds
                FROM recipient_allocations
                GROUP BY recipient_prolific_id
                ORDER BY recipient_prolific_id
                """
            )
            rows = cursor.fetchall()

        return {
            "overview": [
                {"recipient_id": rid, "n_rounds": n}
                for rid, n in rows
            ]
        }

    def before_next_page(self, timeout_happened=False):

        #  delete action
        if self.delete_recipient_id:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM recipient_allocations
                    WHERE recipient_prolific_id = %s
                    """,
                    [self.delete_recipient_id]
                )

        #  view action (display only)
        if self.view_recipient_id:
            self.participant.vars['view_recipient_id'] = self.view_recipient_id
# --------------------------------------------------
# PAGE SEQUENCE
# --------------------------------------------------
page_sequence = [
    #AllocationOverview,
    #Results, #this one and the one above it are for debug mode
    InformedConsent,
    Instructions,
    ComprehensionTest,
    FailedTest,
    Exhausted,
    Results,
    AIdetectionpage,
    #Debriefing,
    ThankYou,
]


# --------------------------------------------------
# ALLOCATION ASSIGNMENT (SAFE)
# --------------------------------------------------
# --------------------------------------------------
# ALLOCATION ASSIGNMENT FROM dictator_values (NEW)
# --------------------------------------------------
# --------------------------------------------------
# ALLOCATION ASSIGNMENT FROM dictator_values (NEW)
# --------------------------------------------------

def assign_allocations_from_dictator_csv_minimal(
    close_old_connections()
    recipient_prolific_id,
    x=100,
):
    """
    Assign EXACTLY x rounds to a recipient from dictator_csv_minimal.

    Rules enforced:
    - Only rounds allowed by random_payoff_part are used
    - No round is ever reused globally
    - Each dictator appears at most once per recipient
    """

    with connection.cursor() as cursor:

        # --------------------------------------------------
        # 1) Idempotency: how many already assigned?
        # --------------------------------------------------
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM recipient_allocations
            WHERE recipient_prolific_id = %s
            """,
            [recipient_prolific_id]
        )
        already_assigned = cursor.fetchone()[0]
        remaining = x - already_assigned

        if remaining <= 0:
            return True

        # --------------------------------------------------
        # 2) Select usable, unused rounds (CORE CHANGE)
        # --------------------------------------------------
        cursor.execute(
            """
            SELECT
                d.participant AS dictator_id,
                r.round_number,
                r.allocation
            FROM dictator_csv_minimal d
            CROSS JOIN LATERAL (
                VALUES
                    (1, allocation_round1),(2, allocation_round2),(3, allocation_round3),(4, allocation_round4),(5, allocation_round5),
                    (6, allocation_round6),(7, allocation_round7),(8, allocation_round8),(9, allocation_round9),(10, allocation_round10),
                    (11, allocation_round11),(12, allocation_round12),(13, allocation_round13),(14, allocation_round14),(15, allocation_round15),
                    (16, allocation_round16),(17, allocation_round17),(18, allocation_round18),(19, allocation_round19),(20, allocation_round20),
                    (21, allocation_round21),(22, allocation_round22),(23, allocation_round23),(24, allocation_round24),(25, allocation_round25),
                    (26, allocation_round26),(27, allocation_round27),(28, allocation_round28),(29, allocation_round29),(30, allocation_round30)
            ) r(round_number, allocation)
            WHERE
                r.allocation IS NOT NULL
                AND (
                    (d.random_payoff_part = 1 AND r.round_number BETWEEN 1  AND 10) OR
                    (d.random_payoff_part = 2 AND r.round_number BETWEEN 11 AND 20) OR
                    (d.random_payoff_part = 3 AND r.round_number BETWEEN 21 AND 30)
                )
                -- ✅ no reuse ever
                AND NOT EXISTS (
                    SELECT 1
                    FROM recipient_allocations ra
                    WHERE ra.dictator_prolific_id = d.participant
                      AND ra.round_number = r.round_number
                )
            ORDER BY RANDOM()
            LIMIT %s
            """,
            [remaining]
        )

        rows = cursor.fetchall()

        # --------------------------------------------------
        # 3) Exhaustion check
        # --------------------------------------------------
        if len(rows) < remaining:
            return False

        # --------------------------------------------------
        # 4) Insert allocations
        # --------------------------------------------------
        cursor.executemany(
            """
            INSERT INTO recipient_allocations
            (recipient_prolific_id,
             dictator_prolific_id,
             round_number,
             part,
             allocated_value)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (
                    recipient_prolific_id,
                    dictator_id,
                    round_number,
                    d_part := None,
                    int(100 - allocation),
                )
                for dictator_id, round_number, allocation in rows
            ]
        )

    return True


def recipient_has_allocations(recipient_prolific_id):
    close_old_connections()   # For when database connection object is stale
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM recipient_allocations
            WHERE recipient_prolific_id = %s
            LIMIT 1
            """,
            [recipient_prolific_id]
        )
        return cursor.fetchone() is not None
# ==================================================
# ASSIGN-ON-FIRST-LOGIN LOGIC
# ==================================================
#def assign_allocations_if_needed(recipient_prolific_id):
#    """
#    Assign allocations to a recipient from exactly ONE allocator
#    and exactly ONE part (1–10, 11–20, or 21–30), ensuring
#    exactly 10 valid rounds exist.
#
#    This function is idempotent: it runs only once per recipient.
#    """
#
#    with connection.cursor() as cursor:
#
#        # --------------------------------------------------
#        # 1) Check if allocations already exist for recipient
#        # --------------------------------------------------
#        cursor.execute(
#            """
#            SELECT 1
#            FROM recipient_allocations
#            WHERE recipient_prolific_id = %s
#            LIMIT 1
#            """,
#            [recipient_prolific_id]
#        )
#        if cursor.fetchone():
#            return  # already assigned, do nothing
#
#        # --------------------------------------------------
#        # 2) Choose ONE allocator + ONE part
#        #    with at least 10 valid rounds
#        # --------------------------------------------------
#        cursor.execute(
#            """
#            SELECT prolific_id, part
#            FROM (
#                SELECT
#                    prolific_id,
#                    CASE
#                        WHEN round_number BETWEEN 1 AND 10 THEN 1
#                        WHEN round_number BETWEEN 11 AND 20 THEN 2
#                        WHEN round_number BETWEEN 21 AND 30 THEN 3
#                    END AS part,
#                    COUNT(*) AS n_rounds
#                FROM dictator_game_player
#                WHERE allocation IS NOT NULL
#                AND prolific_id IS NOT NULL
#                AND round_number BETWEEN 1 AND 30
#                GROUP BY prolific_id, part
#                HAVING COUNT(*) >= 10
#            ) AS valid_allocator_parts
#            WHERE part IS NOT NULL
#            ORDER BY RANDOM()
#            LIMIT 1
#            """
#        )
#        row = cursor.fetchone()
#
#        if not row:
#            raise RuntimeError(
#                "No allocator has 10 valid rounds in any part."
#            )
#
#        allocator_pid, chosen_part = row
#
#        round_start = (chosen_part - 1) * 10 + 1
#        round_end   = chosen_part * 10
#
#        # --------------------------------------------------
#        # 3) Insert EXACTLY those 10 rounds
#        #    Recipient received = 100 - allocation
#        # --------------------------------------------------
#        cursor.execute(
#            """
#            INSERT INTO recipient_allocations
#            (recipient_prolific_id,
#             dictator_prolific_id,
#             round_number,
#             part,
#             allocated_value)
#            SELECT
#                %s,
#                prolific_id,
#                round_number,
#                %s,
#                100 - allocation
#            FROM dictator_game_player
#            WHERE prolific_id = %s
#              AND allocation IS NOT NULL
#              AND round_number BETWEEN %s AND %s
#            ORDER BY round_number
#            """,
#            [
#                recipient_prolific_id,
#                chosen_part,
#                allocator_pid,
#                round_start,
#                round_end,
#            ]
#        )
#
#        # --------------------------------------------------
#        # 4) Sanity check (must be exactly 10 rows)
#        # --------------------------------------------------
#        if cursor.rowcount != 10:
#            raise RuntimeError(
#                f"Expected 10 rounds, inserted {cursor.rowcount} "
#                f"for allocator {allocator_pid}, part {chosen_part}."
#            )

import os
import django
from django.conf import settings

# Temporary safety net to ensure Django settings are loaded
# (used only during local development / debugging)
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


class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass


# --------------------------------------------------
# Player model (recipient only)
# --------------------------------------------------
class Player(BasePlayer):
    
    prolific_id = models.StringField(blank=False,label="Please enter your Prolific ID")

    # ✅ comprehension test fields — must match HTML names
    q1 = models.StringField(choices=['a','b','c','d'])
    q2 = models.StringField(choices=['a','b','c','d'])
    q3 = models.StringField(choices=['a','b','c','d'])
    q4 = models.StringField(choices=['a','b','c','d'])
    q5 = models.StringField(choices=['a','b','c','d'])
    q6 = models.StringField(choices=['a','b','c','d'])
    q7 = models.StringField(choices=['a','b'])
    q8 = models.StringField(choices=['a','b'])

    # ✅ attempt tracking
    comprehension_attempts = models.IntegerField(initial=0)
    is_excluded = models.BooleanField(initial=False)



# --------------------------------------------------
# INFORMED CONSENT (with Prolific ID input)
# --------------------------------------------------
class InformedConsent(Page):
    form_model = 'player'
    form_fields = ['prolific_id']

    def before_next_page(self, timeout_happened=False):
        pid = self.prolific_id.strip()

        # ✅ THIS IS THE CRITICAL LINE
        self.participant.label = pid

        # Optional but safe: assign here
        assign_allocations_if_needed(pid)


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
    form_fields = ['q1','q2','q3','q4','q5','q6','q7','q8']

    def is_displayed(self):
        return not self.field_maybe_none('is_excluded')

    def error_message(self, values):
        correct = {
            'q1': 'b',
            'q2': 'c',
            'q3': 'b',
            'q4': 'd',
            'q5': 'a',
            'q6': 'a',
            'q7': 'b',
            'q8': 'a',
        }

        wrong = [k for k, v in correct.items() if values.get(k) != v]

        if wrong:
            self.comprehension_attempts += 1

            if self.comprehension_attempts >= 3:
                self.is_excluded = True
                return None

            return f"You answered these questions incorrectly: {', '.join(wrong)}"




# --------------------------------------------------
# FAILED TEST
# --------------------------------------------------

class FailedTest(Page):
    def is_displayed(self):
        return self.field_maybe_none('is_excluded')


# --------------------------------------------------
# RESULTS / PAYMENT INFORMATION
# --------------------------------------------------

class Results(Page):

    def is_displayed(self):
        return self.round_number == 1

    def vars_for_template(self):
        recipient_pid = self.participant.label

        # Ensure allocations exist (idempotent)
        assign_allocations_if_needed(recipient_pid)

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
                [recipient_pid]
            )
            rows_raw = cursor.fetchall()

        if not rows_raw:
            raise RuntimeError("No recipient allocations found.")

        # All rows have same allocator and part
        allocator_pid = rows_raw[0][3]
        chosen_part = rows_raw[0][2]

        rows = [
            {
                "round": r,
                "received": allocated,
                "allocated": 100 - allocated,
            }
            for r, allocated, _, _ in rows_raw
        ]

        total_received = sum(r["received"] for r in rows)

        return {
            "allocator_pid": allocator_pid,
            "chosen_part": chosen_part,
            "rows": rows,
            "total_received": total_received,
        }
# --------------------------------------------------
# DEBRIEFING
# --------------------------------------------------
class Debriefing(Page):

    def is_displayed(self):
        return self.round_number == 1

    def vars_for_template(self):
        recipient_pid = self.participant.label

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
                [recipient_pid]
            )
            rows_raw = cursor.fetchall()

        if not rows_raw:
            raise RuntimeError("Debriefing: no recipient_allocations found.")

        allocator_pid = rows_raw[0][3]
        chosen_part = rows_raw[0][2]

        rows = [
            {
                "round": r,
                "allocated": 100 - received,
                "received": received,
            }
            for r, received, _, _ in rows_raw
        ]

        total_received = sum(r["received"] for r in rows)

        return {
            "allocator_pid": allocator_pid,
            "chosen_part": chosen_part,
            "rows": rows,
            "total_received": total_received,
        }
# --------------------------------------------------
# THANK YOU / END PAGE
# --------------------------------------------------
class ThankYou(Page):
    def is_displayed(self):
        return self.round_number == 1


# --------------------------------------------------
# Page order for the recipient flow
# --------------------------------------------------
page_sequence = [
    InformedConsent,
    Instructions,
    ComprehensionTest,
    FailedTest,
    Results,
    Debriefing,
    ThankYou,
]

def assign_allocations_if_needed(recipient_prolific_id):
    """
    Assign allocations to a recipient from ONE randomly selected
    (allocator, part) pair that actually exists in the data.

    No requirement for 10 rounds.
    Inserts all available rounds for that allocator in that part.

    Idempotent: runs only once per recipient.
    """

    with connection.cursor() as cursor:

        # --------------------------------------------------
        # 1) Check if allocations already exist
        # --------------------------------------------------
        cursor.execute(
            """
            SELECT 1
            FROM recipient_allocations
            WHERE recipient_prolific_id = %s
            LIMIT 1
            """,
            [recipient_prolific_id]
        )
        if cursor.fetchone():
            return

        # --------------------------------------------------
        # 2) Choose ONE valid (allocator, part) pair
        # --------------------------------------------------
        cursor.execute(
            """
            SELECT prolific_id, part
            FROM (
                SELECT
                    prolific_id,
                    CASE
                        WHEN round_number BETWEEN 1 AND 10 THEN 1
                        WHEN round_number BETWEEN 11 AND 20 THEN 2
                        WHEN round_number BETWEEN 21 AND 30 THEN 3
                    END AS part
                FROM dictator_game_player
                WHERE allocation IS NOT NULL
                  AND prolific_id IS NOT NULL
            ) AS allocator_parts
            WHERE part IS NOT NULL
            GROUP BY prolific_id, part
            ORDER BY RANDOM()
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("No valid allocator/part combination available.")

        allocator_pid, chosen_part = row

        round_start = (chosen_part - 1) * 10 + 1
        round_end   = chosen_part * 10

        # --------------------------------------------------
        # 3) Insert ALL rounds for that allocator and part
        # --------------------------------------------------
        cursor.execute(
            """
            INSERT INTO recipient_allocations
            (recipient_prolific_id,
             dictator_prolific_id,
             round_number,
             part,
             allocated_value)
            SELECT
                %s,
                prolific_id,
                round_number,
                %s,
                100 - allocation
            FROM dictator_game_player
            WHERE prolific_id = %s
              AND allocation IS NOT NULL
              AND allocation BETWEEN 0 AND 100
              AND round_number BETWEEN %s AND %s
            ORDER BY round_number
            """,
            [
                recipient_prolific_id,
                chosen_part,
                allocator_pid,
                round_start,
                round_end,
            ]
        )

        if cursor.rowcount == 0:
            raise RuntimeError(
                f"Allocator {allocator_pid} has no rounds in part {chosen_part}."
            )


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
#            return  # ✅ already assigned, do nothing
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
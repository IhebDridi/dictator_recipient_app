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
    EXCLUDE_DICTATOR_KEEPS_ZERO = True  #  SWITCH for allocation = 0


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
    q4 = models.StringField(choices=['a', 'b', 'c', 'd'])
    q5 = models.StringField(choices=['a', 'b', 'c', 'd'])
    q6 = models.StringField(choices=['a', 'b', 'c', 'd'])
    q7 = models.StringField(choices=['a', 'b'])
    q8 = models.StringField(choices=['a', 'b'])

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

        # If YES → do nothing else, results must be shown later
        if already_assigned:
            self.participant.vars['exhausted'] = False
            return

        # STEP 2: this is a NEW Prolific ID → try to assign
        success = assign_allocations_if_needed(pid, x=80)

        # STEP 3: mark exhaustion only for NEW IDs
        self.participant.vars['exhausted'] = (success is False)



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
    form_fields = ['q1', 'q2', 'q3', 'q4', 'q5', 'q6', 'q7', 'q8']

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
# RESULTS
# --------------------------------------------------
class Results(Page):

    def is_displayed(self):
        return self.round_number == 1

    def vars_for_template(self):

        view_recipient_id = self.participant.vars.get('view_recipient_id')

        if view_recipient_id:
            recipient_key = view_recipient_id
            viewing_other = True
            already_assigned = False
        else:
            recipient_key = self.participant.label
            viewing_other = False
            already_assigned = self.participant.vars.get('already_assigned', False)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    round_number,
                    allocated_value,
                    dictator_prolific_id
                FROM recipient_allocations
                WHERE recipient_prolific_id = %s
                ORDER BY round_number
                """,
                [recipient_key]
            )
            rows_raw = cursor.fetchall()

        rows = [
            {
                "received": received,
                "allocated": 100 - received,
                "dictator_id": dictator_pid,
            }
            for _, received, dictator_pid in rows_raw
        ]

        return {
            "rows": rows,
            "n_rounds": len(rows),
            "n_dictators": len({pid for _, _, pid in rows_raw}),
            "total_received": sum(r["received"] for r in rows),

            # DEFINE IT HERE
            "recipient_prolific_id": recipient_key,

            "already_assigned": already_assigned,
            "viewing_other": viewing_other,
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

        # ✅ delete action
        if self.delete_recipient_id:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM recipient_allocations
                    WHERE recipient_prolific_id = %s
                    """,
                    [self.delete_recipient_id]
                )

        # ✅ view action (display only)
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
    #Debriefing,
    ThankYou,
]


# --------------------------------------------------
# ALLOCATION ASSIGNMENT (SAFE)
# --------------------------------------------------
def assign_allocations_if_needed(recipient_prolific_id, x=80):
    """
    Assign up to x random dictator rounds to a recipient.

    Rules:
    - A recipient is assigned at most once (idempotent).
    - Dictator rounds are never reused globally.
    - Dictator rounds where the dictator kept 0
      (i.e. allocation = 100) are EXCLUDED.
    - Returns:
        True  -> allocations exist or were successfully created
        False -> no eligible rounds left (pool exhausted)
    """

    with connection.cursor() as cursor:

        # --------------------------------------------------
        # 1) If recipient already has allocations → do nothing
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
            return True

        # --------------------------------------------------
        # 2) Build exclusion condition
        #    Exclude rounds where dictator kept 0
        #    dictator keeps 0 ⇔ allocation = 100
        # --------------------------------------------------
        extra_condition = ""
        if C.EXCLUDE_DICTATOR_KEEPS_ZERO:
            extra_condition = "AND d.allocation <> 0"

        # --------------------------------------------------
        # 3) Select random UNUSED dictator rounds
        # --------------------------------------------------
        cursor.execute(
            f"""
            SELECT
                d.prolific_id,
                d.round_number,
                CASE
                    WHEN d.round_number BETWEEN 1 AND 10 THEN 1
                    WHEN d.round_number BETWEEN 11 AND 20 THEN 2
                    WHEN d.round_number BETWEEN 21 AND 30 THEN 3
                END AS part,
                d.allocation
            FROM dictator_game_player d
            WHERE d.allocation IS NOT NULL
              AND d.prolific_id IS NOT NULL
              {extra_condition}
              AND NOT EXISTS (
                  SELECT 1
                  FROM recipient_allocations r
                  WHERE r.dictator_prolific_id = d.prolific_id
                    AND r.round_number = d.round_number
              )
            ORDER BY RANDOM()
            LIMIT %s
            """,
            [x]
        )

        rows = cursor.fetchall()

        # --------------------------------------------------
        # 4) If nothing eligible left → exhausted
        # --------------------------------------------------
        if not rows:
            return False

        # --------------------------------------------------
        # 5) Insert selected rounds
        #    Recipient receives = 100 - allocation
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
                    dictator_pid,
                    round_number,
                    part,
                    100 - allocation
                )
                for dictator_pid, round_number, part, allocation in rows
            ]
        )

    return True
def recipient_has_allocations(recipient_prolific_id):
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
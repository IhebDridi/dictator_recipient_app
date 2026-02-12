import os
import django
from django.conf import settings

# Temporary safety net to ensure Django settings are loaded
if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    django.setup()

from otree.api import *
from django.db import connection
from django.db import close_old_connections, IntegrityError
import random
import math

close_old_connections()


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
    delete_recipient_id = models.StringField(blank=True)  # to delete recipient info in deubg mode
    view_recipient_id = models.StringField(blank=True)    # to view recipient info in deubg mode
    
    prolific_id = models.StringField(blank=False, label="Please enter your Prolific ID")

    q1 = models.StringField(choices=['a', 'b', 'c', 'd'], blank=True)
    q2 = models.StringField(choices=['a', 'b', 'c', 'd'], blank=True)
    q3 = models.StringField(choices=['a', 'b', 'c', 'd'], blank=True)

    comprehension_attempts = models.IntegerField(initial=0)
    is_excluded = models.BooleanField(initial=False)
    
    total_allocated = models.IntegerField(
        initial=0,
        doc="Sum of all allocations received (raw units)"
    )


# --------------------------------------------------
# INFORMED CONSENT
# --------------------------------------------------
class InformedConsent(Page):
    form_model = 'player'
    form_fields = ['prolific_id']
    def is_displayed(self):
        return self.round_number == 1

    def before_next_page(self, timeout_happened=False):
        pid = self.prolific_id.strip()
        self.participant.label = pid  # display only

        # ✅ AI DETECTION: kick immediately
        if pid == "GeAI12345678900987654321":
            self.participant.vars['ai_detected'] = True
            return

        # STEP 1: check if this Prolific ID already has allocations
        already_assigned = recipient_has_allocations(pid)
        self.participant.vars['already_assigned'] = already_assigned

        # If YES → do nothing else
        #if already_assigned:
            #self.participant.vars['exhausted'] = False
            #return


# --------------------------------------------------
# INSTRUCTIONS
# --------------------------------------------------
class Instructions(Page):
    def is_displayed(self):
        return self.round_number == 1 and not self.participant.vars.get('ai_detected', False)
class Introduction(Page):
    def is_displayed(self):
        return self.round_number == 1


# --------------------------------------------------
# COMPREHENSION TEST
# --------------------------------------------------

class ComprehensionTest(Page):
    form_model = 'player'
    form_fields = ['q1', 'q2', 'q3']

    def is_displayed(self):
        return not self.is_excluded and self.round_number == 1

    def vars_for_template(self):
        return {
            "comp_error_message": self.participant.vars.get("comp_error_message"),
        }

    def error_message(self, values):
        correct_answers = {
            'q1': 'b',
            'q2': 'c',
            'q3': 'b',
        }

        # ❌ WRONG OR UNANSWERED = INCORRECT
        incorrect = [
            q for q, correct in correct_answers.items()
            if values.get(q) != correct
        ]

        if incorrect:
            self.comprehension_attempts += 1
            remaining = 3 - self.comprehension_attempts

            if remaining <= 0:
                # ✅ third failure → exclude and advance
                self.is_excluded = True
                self.participant.vars.pop("comp_error_message", None)
                return None

            # ✅ manual message for template
            self.participant.vars["comp_error_message"] = (
                f"You have failed questions: {', '.join(incorrect)}. "
                f"You now only have {remaining} attempts left."
            )

            # ✅ block page, re-render, no oTree error text
            return " "

        # ✅ all correct → advance
        self.participant.vars.pop("comp_error_message", None)
        return None


# --------------------------------------------------
# FAILED TEST
# --------------------------------------------------
class FailedTest(Page):
    def is_displayed(self):
        return self.is_excluded

    def app_after_this_page(self, upcoming_apps):
        return None  # ends the session for this participant


# --------------------------------------------------
# AI DETECTION PAGE
# --------------------------------------------------
class AIdetectionpage(Page):
    def is_displayed(self):
        return self.participant.vars.get('ai_detected', False)


# --------------------------------------------------
# RESULTS
# --------------------------------------------------

class Results(Page):

    def is_displayed(self):
        return (
            self.round_number == 1
            and not self.is_excluded
            and not self.participant.vars.get('ai_detected', False)
        )

    def vars_for_template(self):

        # ✅ allocate exactly once
        if not self.participant.vars.get("allocations_done", False):
            assign_dictator_rounds_final(
                recipient_prolific_id=self.participant.label,
                x=120,
            )
            self.participant.vars["allocations_done"] = True

        recipient_key = self.participant.label

        # ✅ fetch allocations from FINAL table
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    dictator_round_number,
                    allocated_value
                FROM recipient_allocations_final
                WHERE recipient_prolific_id = %s
                ORDER BY dictator_round_number
                """,
                [recipient_key]
            )
            rows_raw = cursor.fetchall()

        # ✅ use REAL round numbers (no enumerate)
        rows = [
            {
                "round": round_number,
                "received": allocated_value,
                "kept": 100 - allocated_value,
            }
            for (round_number, allocated_value) in rows_raw
        ]

        # ✅ compute totals ONCE and store on Player (export‑safe)
        total_allocated = sum(allocated_value for _, allocated_value in rows_raw)
        self.total_allocated = int(total_allocated)

        # ✅ convert to payout units
        total_cents = math.ceil(total_allocated / 10)
        total_euros = total_cents // 100
        remaining_cents = total_cents % 100

        return {
            "rows": rows,
            "total_allocated": total_allocated,
            "total_cents": total_cents,
            "total_euros": total_euros,
            "remaining_cents": remaining_cents,
        }

    def before_next_page(self, timeout_happened=False):
        pass
# --------------------------------------------------
# THANK YOU
# --------------------------------------------------
class ThankYou(Page):
    def is_displayed(self):
        return (
            self.round_number == 1
            and not self.participant.vars.get('ai_detected', False)
            and not self.is_excluded
        )


class Exhausted(Page):
    def is_displayed(self):
        return False


# --------------------------------------------------
# PAGE SEQUENCE
# --------------------------------------------------
page_sequence = [

    InformedConsent,
    AIdetectionpage,
    Introduction,
    ComprehensionTest,
    FailedTest,
    Results,
    ThankYou,
    #Instructions, #not this one
    
    

    #Exhausted,

]


# --------------------------------------------------
# ALLOCATION ASSIGNMENT (SAFE)
# --------------------------------------------------
def assign_dictator_rounds_to_recipient(
    recipient_prolific_id,
    x=100,
):
    close_old_connections()
    if connection.connection is None:
        connection.ensure_connection()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH picked AS (
                SELECT
                    drc.id,
                    drc.round_number,
                    drc.allocation
                FROM dictator_rounds_clean drc
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM recipient_allocations_test rat
                    WHERE rat.dictator_prolific_id = drc.id::text
                )
                ORDER BY RANDOM()
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            INSERT INTO recipient_allocations_test (
                recipient_prolific_id,
                dictator_prolific_id,
                round_number,
                allocated_value,
                assigned_at
            )
            SELECT
                %s,
                picked.id::text,
                picked.round_number,
                picked.allocation,
                NOW()
            FROM picked
            """,
            [x, recipient_prolific_id]
        )

        # ✅ hard guarantee
        if cursor.rowcount != x:
            raise RuntimeError(
                f"Only {cursor.rowcount} rounds available, cannot assign {x}"
            )





#this function is used to fix the unseccussfull allocations made by users:

def assign_dictator_rounds_too_recipient(
    recipient_prolific_id,
    x=100,
):
    close_old_connections()
    if connection.connection is None:
        connection.ensure_connection()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH picked AS (
                SELECT
                    drc.dictator_id,
                    drc.round_number,
                    drc.allocation
                FROM dictator_remaining_rounds_clean drc
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM recipient_allocations_new ran
                    WHERE ran.dictator_id::integer = drc.dictator_id
                      AND ran.dictator_round_number = drc.round_number
                )
                ORDER BY RANDOM()
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            INSERT INTO recipient_allocations_new (
                recipient_prolific_id,
                dictator_id,
                dictator_round_number,
                allocated_value
            )
            SELECT
                %s,
                picked.dictator_id::text,
                picked.round_number,
                picked.allocation
            FROM picked
            """,
            [x, recipient_prolific_id]
        )

        if cursor.rowcount != x:
            raise RuntimeError(
                f"Only {cursor.rowcount} rounds available, cannot assign {x}"
                
            )
        
def assign_dictator_rounds_final(
    recipient_prolific_id,
    x=100,
):
    close_old_connections()
    if connection.connection is None:
        connection.ensure_connection()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH picked AS (
                SELECT
                    drc.dictator_id,
                    drc.round_number,
                    drc.allocation
                FROM dictator_remaining_rounds_clean drc
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM recipient_allocations_final raf
                    WHERE raf.dictator_id = drc.dictator_id
                      AND raf.dictator_round_number = drc.round_number
                )
                ORDER BY RANDOM()
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            INSERT INTO recipient_allocations_final (
                recipient_prolific_id,
                dictator_id,
                dictator_round_number,
                allocated_value
            )
            SELECT
                %s,
                dictator_id,
                round_number,
                allocation
            FROM picked
            """,
            [x, recipient_prolific_id]
        )

        if cursor.rowcount != x:
            raise RuntimeError(
                f"Only {cursor.rowcount} rounds available, cannot assign {x}"
            )




def recipient_has_allocations(recipient_prolific_id):
    close_old_connections()
    if connection.connection is None:
        connection.ensure_connection()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM recipient_allocations_new
            WHERE recipient_prolific_id = %s
            LIMIT 1
            """,
            [recipient_prolific_id]
        )
        return cursor.fetchone() is not None
    

def custom_export(players):
    rows = [["prolific_id", "total_allocated"]]
    seen = set()

    for p in players:
        pid = p.participant.label
        if not pid or pid in seen:
            continue
        seen.add(pid)
        rows.append([pid, p.total_allocated or 0])

    return rows
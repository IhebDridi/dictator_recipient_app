import os
import django
from django.conf import settings

# Temporary safety net to ensure Django settings are loaded
if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    django.setup()

from otree.api import *
from django.db import connection

from django.db import close_old_connections

close_old_connections()
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

    def vars_for_template(self):
        return {
            "comp_error_message": self.participant.vars.get("comp_error_message"),
        }

    def error_message(self, values):
        correct = {
            "q1": "b",
            "q2": "c",
            "q3": "b",
        }

        wrong = [q for q, ans in correct.items() if values.get(q) != ans]

        if wrong:
            self.comprehension_attempts += 1
            remaining = 3 - self.comprehension_attempts

            if remaining <= 0:
                self.is_excluded = True
                return "You have failed the comprehension test too many times."

            msg = (
                f"You failed questions {', '.join(wrong)}. "
                f"You now only have {remaining} more attempts."
            )

            # ✅ store for custom placement
            self.participant.vars["comp_error_message"] = msg

            # ✅ MUST return non‑empty string to block progression
            return msg


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

# --------------------------------------------------
# RESULTS
# --------------------------------------------------
class Results(Page):

    def is_displayed(self):
        return self.round_number == 1 and not self.is_excluded

    def vars_for_template(self):
        
        recipient_key = self.participant.label

        #  ASSIGN HERE (not in before_next_page)
        success = assign_allocations_from_dictator_csv_minimal(
            recipient_prolific_id=recipient_key,
            x=100,
        )
        self.participant.vars['exhausted'] = False

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

        # --------------------------------------------------
        # PAYOFF CALCULATION
        # --------------------------------------------------
        # 1) Sum over all rows in ECoins
        total_received = sum(r["received"] for r in rows)

        # 2) Convert to cents
        total_cents = total_received / 10

        # 3) Convert to euros if needed
        total_euros = 0
        remaining_cents = total_cents

        if total_cents >= 100:
            total_euros = int(total_cents // 100)
            remaining_cents = total_cents % 100

        return {
            "rows": rows,
            "n_rounds": len(rows),

            # raw payoff units
            "total_received": total_received,   # ECoins
            "total_cents": total_cents,          # cents

            # euro conversion
            "total_euros": total_euros,          # integer euros
            "remaining_cents": remaining_cents,  # cents after euros

            "recipient_prolific_id": recipient_key,
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


# --------------------------------------------------
# PAGE SEQUENCE
# --------------------------------------------------
page_sequence = [
    InformedConsent,
    Instructions,
    ComprehensionTest,
    FailedTest,
    Exhausted,
    Results,
    AIdetectionpage,
    ThankYou,
]


# --------------------------------------------------
# ALLOCATION ASSIGNMENT (SAFE)
# --------------------------------------------------
from django.db import IntegrityError

def assign_allocations_from_dictator_csv_minimal(
    recipient_prolific_id,
    x=100,
    max_retries=5,
):
    for _ in range(max_retries):
        close_old_connections()
        if connection.connection is None:
            connection.ensure_connection()

        with connection.cursor() as cursor:

            # how many already assigned?
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

            # select unused rounds
            cursor.execute(
                """
                SELECT
                    dsr.dictator_id,
                    dsr.round_number,
                    dsr.allocation
                FROM dictator_selected_rounds dsr
                WHERE dsr.allocation IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM recipient_allocations ra
                    WHERE ra.dictator_prolific_id = dsr.dictator_id
                        AND ra.round_number = dsr.round_number
                )
                ORDER BY RANDOM()
                LIMIT %s
                """,
                [remaining]
            )

            rows = cursor.fetchall()

            # 3) If not enough real allocations, fill the rest with zeros
            missing = remaining - len(rows)

            if missing > 0:
                # insert zero rounds (no dictator, no real round_number)
                zero_rows = [
                    (
                        recipient_prolific_id,
                        'ZERO_FILL',   # NOT NULL safe sentinel
                        -i - 1,        # fake round numbers (avoid collision)
                        None,
                        0              # allocated_value = 0
                    )
                    for i in range(missing)
                ]

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
                    zero_rows
                )

            try:
                cursor.executemany(
                    """
                    INSERT INTO recipient_allocations
                    (recipient_prolific_id,
                     dictator_prolific_id,
                     round_number,
                     allocated_value)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            recipient_prolific_id,
                            dictator_id,
                            round_number,
                            int(100 - allocation),
                        )
                        for dictator_id, round_number, allocation in rows
                    ]
                )
                return True

            except IntegrityError:
                # another participant took some rounds → retry
                continue

    return True


def recipient_has_allocations(recipient_prolific_id):
    #  absolutely required
    close_old_connections()

    #  defensive: force reconnect if needed
    if connection.connection is None:
        connection.ensure_connection()

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
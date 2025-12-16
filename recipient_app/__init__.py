import otree.api as ot
import random
from shareddb.models import AllocationRecord

class C(ot.BaseConstants):
    NAME_IN_URL = 'recipient_app'
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = 1

class Subsession(ot.BaseSubsession):
    pass

class Group(ot.BaseGroup):
    pass

class Player(ot.BasePlayer):
    prolific_id = ot.models.StringField()
    payoff_part = ot.models.IntegerField(min=1, max=3, blank=True)
    bonus_cents = ot.models.IntegerField(initial=0)

class InformedConsentReceiver(ot.Page):
    form_model = 'player'
    form_fields = ['prolific_id']

    def error_message_prolific_id(self, value):
        pid = (value or '').strip()
        if len(pid) != 24:
            return "Please enter your valid 24-character Prolific ID."

class PaymentInfoReceiver(ot.Page):
    def vars_for_template(self):
        pp = self.field_maybe_none('payoff_part')
        if pp is None:
            pp = random.randint(1, 3)
            self.payoff_part = pp

        recs = AllocationRecord.objects.filter(
            receiver_prolific_id=self.prolific_id,
            part=pp
        ).order_by('round_in_part')

        rows = [{'round': r.round_in_part,
                 'allocated': r.allocated,
                 'kept': r.kept} for r in recs]
        total_allocated = sum(r['allocated'] for r in rows)
        self.bonus_cents = (int(total_allocated) + 5) // 10

        return dict(
            payoff_part=pp,
            rows=rows,
            total_allocated=total_allocated,
            bonus_cents=self.bonus_cents,
        )

class ThankYouReceiver(ot.Page):
    pass

page_sequence = [InformedConsentReceiver, PaymentInfoReceiver, ThankYouReceiver]
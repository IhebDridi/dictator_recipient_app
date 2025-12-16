from django.db import models

class AllocationRecord(models.Model):
    # Columns match your existing table in Postgres
    session_code = models.CharField(max_length=64)
    experiment   = models.CharField(max_length=100, blank=True)
    app_name     = models.CharField(max_length=100, blank=True)

    allocator_prolific_id = models.CharField(max_length=64, db_index=True)
    receiver_prolific_id  = models.CharField(max_length=64, blank=True, db_index=True)

    part = models.IntegerField()
    round_in_part = models.IntegerField()

    allocated = models.IntegerField()
    kept      = models.IntegerField()

    assigned    = models.BooleanField(default=False)
    assigned_at = models.DateTimeField(null=True, blank=True)

    receiver_payoff_part = models.IntegerField(null=True, blank=True)
    created_at           = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'allocation_record'  # use actual name from Postgres
        managed = False  # don't let Django create/alter this table
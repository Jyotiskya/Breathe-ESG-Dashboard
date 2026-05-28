import uuid
from django.db import models
from django.contrib.auth.models import User


# ---------------------------------------------------------------------------
# TENANT
# ---------------------------------------------------------------------------

class Company(models.Model):
    """
    One row per client. Every other model foreign-keys here so a single
    deployment can serve multiple enterprise clients without data leakage.
    This is the multi-tenancy anchor the assignment explicitly requires.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# INGESTION BATCH
# ---------------------------------------------------------------------------

class IngestionBatch(models.Model):
    """
    Tracks a single upload/pull event. Every EmissionRecord links back here
    so analysts can say "show me everything from the 14-May SAP upload" or
    "re-ingest this file". Without this, there's no way to trace which file
    produced which rows — a real audit requirement.
    """
    SOURCE_CHOICES = [
        ('SAP', 'SAP Fuel & Procurement'),
        ('UTILITY', 'Utility / Electricity'),
        ('TRAVEL', 'Corporate Travel'),
    ]

    STATUS_CHOICES = [
        ('PROCESSING', 'Processing'),
        ('COMPLETE', 'Complete'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='batches')
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES)

    # Stores the original filename or API endpoint pulled from. Null for
    # manual paste ingestion.
    source_identifier = models.CharField(max_length=500, blank=True, null=True)

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batches_uploaded'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PROCESSING')
    error_message = models.TextField(blank=True, null=True)  # stores parse errors

    row_count = models.IntegerField(default=0)
    failed_row_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.source_type} batch @ {self.created_at:%Y-%m-%d %H:%M} ({self.company})"


# ---------------------------------------------------------------------------
# EMISSION RECORD
# ---------------------------------------------------------------------------

class EmissionRecord(models.Model):
    """
    One row = one activity event (a fuel fill, a monthly electricity bill,
    a flight segment). NOT one row per kg CO2e — the activity data is the
    source of truth; CO2e is derived.

    Key design choices:
    - raw_* fields store exactly what came in, untouched.
    - normalized_quantity is always in a canonical unit per source type
      (litres for SAP fuel, kWh for utility, km for travel distance).
    - co2e_kg is the final calculated figure. Null until emission factor applied.
    - scope is set at ingest time based on source + category rules.
    """

    SCOPE_CHOICES = [
        ('1', 'Scope 1 — Direct emissions'),
        ('2', 'Scope 2 — Purchased electricity/heat'),
        ('3', 'Scope 3 — Value chain'),
    ]

    SOURCE_CHOICES = [
        ('SAP', 'SAP Fuel & Procurement'),
        ('UTILITY', 'Utility / Electricity'),
        ('TRAVEL', 'Corporate Travel'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    TRAVEL_CATEGORY_CHOICES = [
        ('flight', 'Flight'),
        ('hotel', 'Hotel'),
        ('ground_taxi', 'Ground — Taxi/Rideshare'),
        ('ground_rail', 'Ground — Rail'),
        ('ground_rental', 'Ground — Car Rental'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # -- Tenant & provenance --------------------------------------------------
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='records')
    batch = models.ForeignKey(
        IngestionBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='records'
    )
    # Which row inside the source file this came from. Helps re-trace parse errors.
    source_row_index = models.IntegerField(null=True, blank=True)

    # -- Source classification ------------------------------------------------
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    scope = models.CharField(max_length=1, choices=SCOPE_CHOICES)

    # High-level grouping: "diesel", "electricity", "flight", "hotel", etc.
    category = models.CharField(max_length=100)

    # -- Raw fields (never mutated after ingest) ------------------------------
    # Storing raw values is non-negotiable for audit. If our normalisation
    # logic had a bug, we need to be able to re-derive without re-uploading.
    raw_quantity = models.FloatField()
    raw_unit = models.CharField(max_length=50)
    raw_date = models.CharField(max_length=50)        # exactly as it appeared
    raw_period_start = models.CharField(max_length=50, blank=True, null=True)
    raw_period_end = models.CharField(max_length=50, blank=True, null=True)

    # SAP-specific raw fields
    raw_plant_code = models.CharField(max_length=50, blank=True, null=True)
    raw_material_code = models.CharField(max_length=50, blank=True, null=True)

    # Utility-specific
    raw_meter_id = models.CharField(max_length=100, blank=True, null=True)
    raw_tariff = models.CharField(max_length=100, blank=True, null=True)

    # Travel-specific
    raw_origin = models.CharField(max_length=10, blank=True, null=True)   # airport/city code
    raw_destination = models.CharField(max_length=10, blank=True, null=True)
    raw_travel_class = models.CharField(max_length=50, blank=True, null=True)
    travel_category = models.CharField(
        max_length=20,
        choices=TRAVEL_CATEGORY_CHOICES,
        blank=True,
        null=True
    )

    # -- Normalised fields (computed at ingest) --------------------------------
    # SAP fuel → litres | SAP procurement mass → kg
    # Utility → kWh
    # Travel distance → km  |  hotel → nights (dimensionless count)
    normalized_quantity = models.FloatField()
    normalized_unit = models.CharField(max_length=20)
    activity_date = models.DateField()  # parsed from raw_date

    # -- Emissions calculation -------------------------------------------------
    # emission_factor: kgCO2e per normalised unit (e.g. kgCO2e/litre).
    # Stored here so we can audit which factor was used at the time of calc.
    # Null = not yet calculated.
    emission_factor = models.FloatField(null=True, blank=True)
    emission_factor_source = models.CharField(max_length=200, blank=True, null=True)
    co2e_kg = models.FloatField(null=True, blank=True)

    # -- Quality flags ---------------------------------------------------------
    suspicious = models.BooleanField(default=False)
    # Free-text reason so the analyst knows *why* it was flagged, not just that it was.
    suspicious_reason = models.CharField(max_length=500, blank=True, null=True)

    # -- Review workflow -------------------------------------------------------
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_records'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True, null=True)

    # -- Timestamps ------------------------------------------------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-activity_date']
        indexes = [
            models.Index(fields=['company', 'source_type']),
            models.Index(fields=['company', 'scope']),
            models.Index(fields=['status']),
            models.Index(fields=['suspicious']),
            models.Index(fields=['activity_date']),
        ]

    def flag_suspicious(self, reason: str):
        """
        Call this during ingestion rather than relying on save() magic.
        Separating flagging from persistence means tests can inspect the
        reason without hitting the database.
        """
        self.suspicious = True
        self.suspicious_reason = reason

    def __str__(self):
        return f"{self.source_type} | {self.category} | {self.activity_date} | {self.co2e_kg} kgCO2e"


# ---------------------------------------------------------------------------
# AUDIT LOG
# ---------------------------------------------------------------------------

class AuditLog(models.Model):
    """
    Immutable append-only log. We never update or delete rows here.
    Covers the full lifecycle: INGESTED → (FLAGGED) → APPROVED/REJECTED.
    Required for the "sign-off before auditors" workflow in the brief.
    """

    ACTION_CHOICES = [
        ('INGESTED', 'Ingested'),
        ('FLAGGED', 'Flagged as suspicious'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('EDITED', 'Edited'),        # analyst corrected a value before approving
        ('REOPENED', 'Reopened'),    # approved record sent back for re-review
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(EmissionRecord, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)

    # Who did it. Null only for system-generated actions (INGESTED, FLAGGED).
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_actions'
    )

    # JSON snapshot of the record at the time of action. Lets us show
    # "what changed" diffs in the UI without a full versioning library.
    # E.g. {"quantity": 450, "unit": "litres"} before an edit.
    before_snapshot = models.JSONField(null=True, blank=True)
    after_snapshot = models.JSONField(null=True, blank=True)

    note = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']
        # Prevent accidental updates — audit rows are write-once.
        # Enforce this in serializers/views too, not just here.

    def __str__(self):
        actor_name = self.actor.username if self.actor else "system"
        return f"{self.action} by {actor_name} @ {self.timestamp:%Y-%m-%d %H:%M}"


# ---------------------------------------------------------------------------
# FAILED ROW
# ---------------------------------------------------------------------------

class FailedRow(models.Model):
    """
    When a row in an uploaded file can't be parsed or normalised, we store
    it here instead of silently dropping it. The analyst dashboard shows
    failed rows alongside pending ones so nothing falls through the cracks.

    This was a deliberate choice over raising an exception and rejecting
    the whole file — partial ingestion is more useful in practice.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(IngestionBatch, on_delete=models.CASCADE, related_name='failed_rows')
    row_index = models.IntegerField()
    raw_data = models.JSONField()           # the whole row as a dict
    error_message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Failed row {self.row_index} in batch {self.batch_id}: {self.error_message[:80]}"
from rest_framework import serializers
from .models import EmissionRecord, Company, AuditLog, IngestionBatch, FailedRow


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'


class IngestionBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngestionBatch
        fields = [
            'id', 'company', 'source_type', 'source_identifier',
            'status', 'row_count', 'failed_row_count',
            'created_at', 'completed_at', 'error_message',
        ]


class EmissionRecordSerializer(serializers.ModelSerializer):
    # Flattened company name so the frontend doesn't need a second request
    company_name = serializers.CharField(source='company.name', read_only=True)
    batch_source = serializers.CharField(source='batch.source_identifier', read_only=True)

    class Meta:
        model = EmissionRecord
        fields = [
            # Identity
            'id',
            'company_name',
            'batch_source',
            'source_row_index',

            # Classification
            'source_type',
            'scope',
            'category',
            'travel_category',

            # Raw (what came in)
            'raw_quantity',
            'raw_unit',
            'raw_date',
            'raw_period_start',
            'raw_period_end',
            'raw_plant_code',
            'raw_material_code',
            'raw_meter_id',
            'raw_tariff',
            'raw_origin',
            'raw_destination',
            'raw_travel_class',

            # Normalised
            'normalized_quantity',
            'normalized_unit',
            'activity_date',

            # Emissions
            'emission_factor',
            'emission_factor_source',
            'co2e_kg',

            # Quality
            'suspicious',
            'suspicious_reason',

            # Review
            'status',
            'reviewed_at',
            'reviewer_note',

            # Timestamps
            'created_at',
            'updated_at',
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    # Include enough record context to render the audit trail without joins
    record_id = serializers.UUIDField(source='record.id', read_only=True)
    record_category = serializers.CharField(source='record.category', read_only=True)
    record_source = serializers.CharField(source='record.source_type', read_only=True)
    actor_name = serializers.CharField(source='actor.username', read_only=True, default='system')

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'record_id',
            'record_category',
            'record_source',
            'action',
            'actor_name',
            'note',
            'before_snapshot',
            'after_snapshot',
            'timestamp',
        ]


class FailedRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = FailedRow
        fields = ['id', 'batch', 'row_index', 'raw_data', 'error_message', 'created_at']

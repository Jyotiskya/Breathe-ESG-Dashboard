from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from .models import EmissionRecord, Company, AuditLog, IngestionBatch, FailedRow
from .serializers import (
    EmissionRecordSerializer,
    CompanySerializer,
    AuditLogSerializer,
    IngestionBatchSerializer,
)
import pandas as pd
from datetime import datetime


# ---------------------------------------------------------------------------
# EMISSION FACTORS
# kgCO2e per unit. Sources: DEFRA 2023, GHG Protocol.
# Stored here so the review can see exactly what was used.
# ---------------------------------------------------------------------------
EMISSION_FACTORS = {
    # SAP fuel (per litre)
    'diesel':   {'factor': 2.68,  'unit': 'L',      'source': 'DEFRA 2023 - Diesel'},
    'petrol':   {'factor': 2.31,  'unit': 'L',      'source': 'DEFRA 2023 - Petrol'},
    'hfo':      {'factor': 3.17,  'unit': 'L',      'source': 'DEFRA 2023 - Heavy Fuel Oil'},
    'lpg':      {'factor': 2.94,  'unit': 'kg',     'source': 'DEFRA 2023 - LPG'},

    # Utility (per kWh) - India grid average
    'electricity': {'factor': 0.708, 'unit': 'kWh', 'source': 'CEA India 2023 Grid Emission Factor'},

    # Travel - flights (per km per passenger)
    'flight_economy':  {'factor': 0.255, 'unit': 'km', 'source': 'DEFRA 2023 - Long haul economy'},
    'flight_business': {'factor': 0.510, 'unit': 'km', 'source': 'DEFRA 2023 - Long haul business (2x)'},

    # Travel - hotels (per night)
    'hotel':        {'factor': 31.2,  'unit': 'night', 'source': 'DEFRA 2023 - Hotel stay'},

    # Travel - ground (per trip, rough average)
    'ground_taxi':  {'factor': 3.5,   'unit': 'trip',  'source': 'DEFRA 2023 - Taxi avg trip'},
    'ground_rail':  {'factor': 1.2,   'unit': 'trip',  'source': 'DEFRA 2023 - Rail avg trip'},
    'ground_rental':{'factor': 8.0,   'unit': 'trip',  'source': 'DEFRA 2023 - Car rental avg trip'},
}

# Airport-pair distances (km) for routes without distance_km in the CSV.
# In production this would be an IATA great-circle lookup.
AIRPORT_DISTANCES = {
    ('BLR', 'LHR'): 8379, ('LHR', 'BLR'): 8379,
    ('BOM', 'SIN'): 4463, ('SIN', 'BOM'): 4463,
    ('DEL', 'DXB'): 2194, ('DXB', 'DEL'): 2194,
    ('BLR', 'BOM'): 1090, ('BOM', 'BLR'): 1090,
    ('BLR', 'JFK'): 13696, ('JFK', 'BLR'): 13696,
    ('DEL', 'CDG'): 6595, ('CDG', 'DEL'): 6595,
    ('BOM', 'KUL'): 4370, ('KUL', 'BOM'): 4370,
    ('BLR', 'HYD'): 500,  ('HYD', 'BLR'): 500,
    ('BLR', 'CCU'): 1670, ('CCU', 'BLR'): 1670,
    ('JFK', 'LAX'): 4500, ('LAX', 'JFK'): 4500,
    ('BOM', 'NRT'): 6760, ('NRT', 'BOM'): 6760,
    ('BLR', 'SFO'): 14060, ('SFO', 'BLR'): 14060,
    ('DEL', 'LHR'): 6741, ('LHR', 'DEL'): 6741,
}

# SAP material code → fuel type mapping (plant-specific codes are opaque without this)
SAP_MATERIAL_MAP = {
    'DIESEL-001': 'diesel',
    'PETROL-002': 'petrol',
    'LPG-003':    'lpg',
    'HFO-004':    'hfo',
}

# Unit normalisation for SAP
UNIT_CONVERSIONS = {
    'L':   ('L',  1.0),
    'LTR': ('L',  1.0),
    'GAL': ('L',  3.785),
    'KG':  ('kg', 1.0),
    'T':   ('kg', 1000.0),
    'KWH': ('kWh', 1.0),
    'MWH': ('kWh', 1000.0),
}


# ---------------------------------------------------------------------------
# PARSERS — one per source type
# Each returns (records_to_create, failed_rows)
# ---------------------------------------------------------------------------

def parse_sap(df, company, batch):
    records, failures = [], []

    required = {'MATNR', 'MENGE', 'MEINS', 'BUDAT', 'WERKS'}
    missing = required - set(df.columns)
    if missing:
        return [], [{'row': 0, 'data': {}, 'error': f'Missing SAP columns: {missing}'}]

    for i, row in df.iterrows():
        try:
            mat_code = str(row['MATNR']).strip()
            fuel_type = SAP_MATERIAL_MAP.get(mat_code)
            if not fuel_type:
                raise ValueError(f"Unknown material code '{mat_code}' — not in lookup table")

            raw_qty = float(row['MENGE'])
            raw_unit = str(row['MEINS']).strip().upper()

            norm_unit, multiplier = UNIT_CONVERSIONS.get(raw_unit, (raw_unit, 1.0))
            norm_qty = raw_qty * multiplier

            # Parse SAP date: YYYYMMDD
            raw_date = str(row['BUDAT']).strip()
            activity_date = datetime.strptime(raw_date, '%Y%m%d').date()

            ef_key = fuel_type
            ef_data = EMISSION_FACTORS.get(ef_key)
            co2e = round(norm_qty * ef_data['factor'], 3) if ef_data else None

            rec = EmissionRecord(
                company=company,
                batch=batch,
                source_row_index=i,
                source_type='SAP',
                scope='1',  # Direct combustion = Scope 1
                category=fuel_type,
                raw_quantity=raw_qty,
                raw_unit=raw_unit,
                raw_date=raw_date,
                raw_plant_code=str(row.get('WERKS', '')).strip(),
                raw_material_code=mat_code,
                normalized_quantity=norm_qty,
                normalized_unit=norm_unit,
                activity_date=activity_date,
                emission_factor=ef_data['factor'] if ef_data else None,
                emission_factor_source=ef_data['source'] if ef_data else None,
                co2e_kg=co2e,
            )

            # Flag suspicious rows
            if raw_qty <= 0:
                rec.flag_suspicious(f"Negative or zero quantity ({raw_qty}) — may be a reversal entry")
            elif norm_qty > 20000:
                rec.flag_suspicious(f"Quantity {norm_qty}L exceeds 20,000L threshold — verify with plant manager")

            records.append(rec)

        except Exception as e:
            failures.append({'row': i + 2, 'data': row.to_dict(), 'error': str(e)})

    return records, failures


def parse_utility(df, company, batch):
    records, failures = [], []

    required = {'meter_id', 'consumption', 'unit', 'billing_period_start', 'billing_period_end'}
    missing = required - set(df.columns)
    if missing:
        return [], [{'row': 0, 'data': {}, 'error': f'Missing utility columns: {missing}'}]

    # Detect duplicate meter+period combos before creating records
    seen = set()

    for i, row in df.iterrows():
        try:
            meter_id = str(row['meter_id']).strip()
            period_start = str(row['billing_period_start']).strip()
            period_end = str(row['billing_period_end']).strip()

            dup_key = (meter_id, period_start, period_end)
            is_duplicate = dup_key in seen
            seen.add(dup_key)

            raw_qty = float(row['consumption'])
            raw_unit = str(row['unit']).strip().upper()

            norm_unit, multiplier = UNIT_CONVERSIONS.get(raw_unit, (raw_unit, 1.0))
            norm_qty = raw_qty * multiplier

            activity_date = datetime.strptime(period_end, '%Y-%m-%d').date()

            ef_data = EMISSION_FACTORS['electricity']
            co2e = round(norm_qty * ef_data['factor'], 3)

            rec = EmissionRecord(
                company=company,
                batch=batch,
                source_row_index=i,
                source_type='UTILITY',
                scope='2',  # Purchased electricity = Scope 2
                category='electricity',
                raw_quantity=raw_qty,
                raw_unit=raw_unit,
                raw_date=period_end,
                raw_period_start=period_start,
                raw_period_end=period_end,
                raw_meter_id=meter_id,
                raw_tariff=str(row.get('tariff_code', '')).strip(),
                normalized_quantity=norm_qty,
                normalized_unit=norm_unit,
                activity_date=activity_date,
                emission_factor=ef_data['factor'],
                emission_factor_source=ef_data['source'],
                co2e_kg=co2e,
            )

            # Validate: previous + consumption should equal current reading
            try:
                prev = float(row['previous_reading'])
                curr = float(row['current_reading'])
                expected = round(curr - prev, 2)
                if abs(expected - raw_qty) > 1.0:
                    rec.flag_suspicious(
                        f"Meter reading mismatch: {curr} - {prev} = {expected}, but consumption listed as {raw_qty}"
                    )
            except (KeyError, ValueError):
                pass  # columns may not always be present

            if is_duplicate:
                rec.flag_suspicious(
                    f"Duplicate billing period: meter {meter_id} for {period_start}–{period_end} appears more than once"
                )

            # Spike detection: flag if > 3x typical for this meter
            # Simple version: flag if > 15,000 kWh for non-data-centre meters
            if norm_qty > 15000 and 'data' not in str(row.get('site_name', '')).lower():
                rec.flag_suspicious(
                    f"Consumption {norm_qty} kWh is unusually high for a non-data-centre meter"
                )

            records.append(rec)

        except Exception as e:
            failures.append({'row': i + 2, 'data': row.to_dict(), 'error': str(e)})

    return records, failures


def parse_travel(df, company, batch):
    records, failures = [], []

    required = {'trip_id', 'travel_category', 'travel_date'}
    missing = required - set(df.columns)
    if missing:
        return [], [{'row': 0, 'data': {}, 'error': f'Missing travel columns: {missing}'}]

    for i, row in df.iterrows():
        try:
            travel_cat = str(row['travel_category']).strip().lower()
            raw_date = str(row['travel_date']).strip()
            activity_date = datetime.strptime(raw_date, '%Y-%m-%d').date()

            origin = str(row.get('origin', '') or '').strip().upper()
            destination = str(row.get('destination', '') or '').strip().upper()
            cabin = str(row.get('cabin_class', '') or '').strip().lower()

            # --- Determine quantity and unit per travel category ---
            if travel_cat == 'flight':
                # Use provided distance or look up from airport pair
                dist_raw = row.get('distance_km')
                if pd.notna(dist_raw) and str(dist_raw).strip() not in ('', 'nan'):
                    norm_qty = float(dist_raw)
                elif origin and destination:
                    norm_qty = AIRPORT_DISTANCES.get((origin, destination))
                    if norm_qty is None:
                        raise ValueError(
                            f"No distance for route {origin}→{destination} and none provided in CSV"
                        )
                else:
                    raise ValueError("Flight row has no distance_km and no origin/destination codes")

                norm_unit = 'km'
                ef_key = 'flight_business' if cabin == 'business' else 'flight_economy'
                raw_qty = norm_qty
                raw_unit = 'km'

            elif travel_cat == 'hotel':
                nights_raw = row.get('nights')
                if pd.isna(nights_raw) or str(nights_raw).strip() in ('', 'nan'):
                    # Derive from return_date - travel_date
                    return_raw = str(row.get('return_date', '') or '').strip()
                    if return_raw:
                        ret_date = datetime.strptime(return_raw, '%Y-%m-%d').date()
                        norm_qty = (ret_date - activity_date).days
                    else:
                        raise ValueError("Hotel row has no 'nights' and no 'return_date' to derive from")
                else:
                    norm_qty = float(nights_raw)
                norm_unit = 'night'
                ef_key = 'hotel'
                raw_qty = norm_qty
                raw_unit = 'night'

            elif travel_cat in ('ground_taxi', 'ground_rail', 'ground_rental'):
                norm_qty = 1.0
                norm_unit = 'trip'
                ef_key = travel_cat
                raw_qty = 1.0
                raw_unit = 'trip'

            else:
                raise ValueError(f"Unknown travel_category '{travel_cat}'")

            ef_data = EMISSION_FACTORS.get(ef_key)
            co2e = round(norm_qty * ef_data['factor'], 3) if ef_data else None

            rec = EmissionRecord(
                company=company,
                batch=batch,
                source_row_index=i,
                source_type='TRAVEL',
                scope='3',  # Business travel = Scope 3
                category=travel_cat,
                travel_category=travel_cat,
                raw_quantity=raw_qty,
                raw_unit=raw_unit,
                raw_date=raw_date,
                raw_origin=origin or None,
                raw_destination=destination or None,
                raw_travel_class=cabin or None,
                normalized_quantity=norm_qty,
                normalized_unit=norm_unit,
                activity_date=activity_date,
                emission_factor=ef_data['factor'] if ef_data else None,
                emission_factor_source=ef_data['source'] if ef_data else None,
                co2e_kg=co2e,
            )

            # Flag long-haul business class — highest emitter per trip
            if travel_cat == 'flight' and cabin == 'business' and norm_qty > 5000:
                rec.flag_suspicious(
                    f"Long-haul business class flight ({origin}→{destination}, {norm_qty}km) — "
                    f"high-emission trip, verify approval"
                )

            records.append(rec)

        except Exception as e:
            failures.append({'row': i + 2, 'data': row.to_dict(), 'error': str(e)})

    return records, failures


# ---------------------------------------------------------------------------
# VIEWS
# ---------------------------------------------------------------------------

@api_view(['GET'])
def get_records(request):
    source = request.query_params.get('source')
    status_filter = request.query_params.get('status')
    suspicious_only = request.query_params.get('suspicious')

    qs = EmissionRecord.objects.select_related('company', 'batch').order_by('-activity_date')

    if source:
        qs = qs.filter(source_type=source.upper())
    if status_filter:
        qs = qs.filter(status=status_filter.upper())
    if suspicious_only == 'true':
        qs = qs.filter(suspicious=True)

    serializer = EmissionRecordSerializer(qs, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def upload_file(request):
    if 'file' not in request.FILES:
        return Response({"error": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)

    source_type = request.data.get('source_type', '').upper().strip()
    if source_type not in ('SAP', 'UTILITY', 'TRAVEL'):
        return Response(
            {"error": "source_type must be SAP, UTILITY, or TRAVEL."},
            status=status.HTTP_400_BAD_REQUEST
        )

    file = request.FILES['file']
    try:
        df = pd.read_csv(file)
    except Exception as e:
        return Response({"error": f"Failed to parse CSV: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    company, _ = Company.objects.get_or_create(name="Demo Company")

    batch = IngestionBatch.objects.create(
        company=company,
        source_type=source_type,
        source_identifier=file.name,
        status='PROCESSING',
    )

    # Route to the correct parser
    parsers = {'SAP': parse_sap, 'UTILITY': parse_utility, 'TRAVEL': parse_travel}
    records_to_create, failures = parsers[source_type](df, company, batch)

    # Bulk save good rows
    if records_to_create:
        EmissionRecord.objects.bulk_create(records_to_create)

        # Write INGESTED audit log entries
        created_records = EmissionRecord.objects.filter(batch=batch)
        AuditLog.objects.bulk_create([
            AuditLog(record=r, action='INGESTED')
            for r in created_records
        ])

        # Write FLAGGED audit entries for suspicious rows
        AuditLog.objects.bulk_create([
            AuditLog(record=r, action='FLAGGED', note=r.suspicious_reason)
            for r in created_records if r.suspicious
        ])

    # Save failed rows
    if failures:
        FailedRow.objects.bulk_create([
            FailedRow(
                batch=batch,
                row_index=f['row'],
                raw_data=f['data'],
                error_message=f['error'],
            )
            for f in failures
        ])

    # Update batch summary
    batch.status = 'COMPLETE'
    batch.row_count = len(records_to_create)
    batch.failed_row_count = len(failures)
    batch.completed_at = timezone.now()
    batch.save()

    return Response({
        "message": f"Ingested {len(records_to_create)} records, {len(failures)} failed.",
        "batch_id": str(batch.id),
        "failed_rows": failures,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
def approve_record(request, pk):
    try:
        record = EmissionRecord.objects.get(id=pk)
    except EmissionRecord.DoesNotExist:
        return Response({"error": "Record not found."}, status=status.HTTP_404_NOT_FOUND)

    record.status = 'APPROVED'
    record.reviewed_at = timezone.now()
    record.save()

    AuditLog.objects.create(record=record, action='APPROVED',
                            note=request.data.get('note', ''))
    return Response({"message": "Record approved."})


@api_view(['POST'])
def reject_record(request, pk):
    try:
        record = EmissionRecord.objects.get(id=pk)
    except EmissionRecord.DoesNotExist:
        return Response({"error": "Record not found."}, status=status.HTTP_404_NOT_FOUND)

    record.status = 'REJECTED'
    record.reviewed_at = timezone.now()
    record.save()

    AuditLog.objects.create(record=record, action='REJECTED',
                            note=request.data.get('note', ''))
    return Response({"message": "Record rejected."})


@api_view(['GET'])
def suspicious_records(request):
    records = EmissionRecord.objects.filter(suspicious=True).order_by('-activity_date')
    serializer = EmissionRecordSerializer(records, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def audit_logs(request):
    logs = AuditLog.objects.select_related('record').order_by('-timestamp')
    serializer = AuditLogSerializer(logs, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def batch_list(request):
    batches = IngestionBatch.objects.filter(
        company__name="Demo Company"
    ).order_by('-created_at')
    serializer = IngestionBatchSerializer(batches, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def dashboard_summary(request):
    """Single endpoint the React dashboard uses for all counts."""
    total = EmissionRecord.objects.count()
    return Response({
        "total": total,
        "pending": EmissionRecord.objects.filter(status='PENDING').count(),
        "approved": EmissionRecord.objects.filter(status='APPROVED').count(),
        "rejected": EmissionRecord.objects.filter(status='REJECTED').count(),
        "suspicious": EmissionRecord.objects.filter(suspicious=True).count(),
        "total_co2e_kg": sum(
            r.co2e_kg for r in EmissionRecord.objects.all() if r.co2e_kg
        ),
        "by_scope": {
            "1": EmissionRecord.objects.filter(scope='1').count(),
            "2": EmissionRecord.objects.filter(scope='2').count(),
            "3": EmissionRecord.objects.filter(scope='3').count(),
        },
        "by_source": {
            "SAP": EmissionRecord.objects.filter(source_type='SAP').count(),
            "UTILITY": EmissionRecord.objects.filter(source_type='UTILITY').count(),
            "TRAVEL": EmissionRecord.objects.filter(source_type='TRAVEL').count(),
        }
    })

        # Breathe ESG — Emissions Ingestion Prototype

A Django REST + React prototype for ingesting, normalising, and reviewing emissions data from three enterprise source types: SAP fuel/procurement exports, utility electricity billing CSVs, and corporate travel platform exports.

---

## What it does

The system ingests raw activity data from three sources, normalises units, calculates CO₂e using published emission factors, flags suspicious rows automatically, and surfaces everything in a review dashboard where an analyst can approve or reject records before they're locked for audit.

Each upload creates an `IngestionBatch` record so every `EmissionRecord` can be traced back to the specific file that produced it. Failed rows are stored separately rather than silently dropped — partial ingestion is intentional.

---

## Project structure

```
breathe-esg/
├── backend/
│   ├── backend/          # Django settings, urls.py, wsgi
│   ├── emissions/        # Models, views, serializers, parsers
│   │   ├── models.py
│   │   ├── views.py
│   │   └── serializers.py
│   └── manage.py
├── frontend/
│   └── src/
│       ├── App.js
│       └── App.css
├── sap_data.csv
├── travel_data.csv
├── utility_data.csv
├── MODEL.md
├── DECISIONS.md
├── TRADEOFFS.md
├── SOURCES.md
└── README.md
```

---

## Setup

### Requirements

- Python 3.10+
- Node.js 18+
- pip

### Backend

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install django djangorestframework django-cors-headers pandas

python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser 
python manage.py runserver
```

Backend runs at `http://127.0.0.1:8000`

### Frontend

```bash
cd frontend
npm install
npm start
```

Frontend runs at `http://localhost:3000`

---

## Uploading sample data

The three sample CSVs in the root of the repo cover January–March 2024 across a fictional multi-site Indian enterprise client. Each file must be uploaded with its `source_type` specified.

Run the upload script from the project root (with the Django server running):

```bash
python upload.py
```

Or upload manually with curl:

```bash
curl -X POST http://127.0.0.1:8000/api/upload/ \
  -F "file=@sap_data.csv" \
  -F "source_type=SAP"

curl -X POST http://127.0.0.1:8000/api/upload/ \
  -F "file=@utility_data.csv" \
  -F "source_type=UTILITY"

curl -X POST http://127.0.0.1:8000/api/upload/ \
  -F "file=@travel_data.csv" \
  -F "source_type=TRAVEL"
```

After uploading all three files you should see 70 records in the dashboard: 20 SAP rows, 20 utility rows, 30 travel rows.

---

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/records/` | All emission records. Supports `?source=SAP`, `?status=PENDING`, `?suspicious=true` |
| POST | `/api/upload/` | Upload a CSV. Requires `file` and `source_type` (SAP / UTILITY / TRAVEL) |
| POST | `/api/approve/<id>/` | Approve a record by UUID |
| POST | `/api/reject/<id>/` | Reject a record by UUID |
| GET | `/api/summary/` | Dashboard counts: total, pending, approved, rejected, suspicious, CO₂e by scope and source |
| GET | `/api/batches/` | List of ingestion batches with row counts and status |
| GET | `/api/audit-logs/` | Full audit trail |
| GET | `/api/suspicious/` | Suspicious records only |

---

## Data sources and emission factors

### SAP
Format modelled on SAP MM flat file export (transaction ME2M). German column headers (`MENGE`, `MEINS`, `BUDAT`, `WERKS`, `MATNR`). Dates in YYYYMMDD. Material codes mapped to fuel types via a lookup table in `views.py`.

Emission factors (DEFRA 2023):
- Diesel: 2.68 kgCO₂e/litre
- Petrol: 2.31 kgCO₂e/litre
- LPG: 2.94 kgCO₂e/kg
- Heavy fuel oil: 3.17 kgCO₂e/litre

Scope: **1** (direct combustion)

### Utility
Format modelled on BESCOM/Tata Power commercial portal CSV export. Includes previous and current meter readings so the parser validates that `current − previous = consumption`. Duplicate billing periods flagged automatically.

Emission factor: **0.708 kgCO₂e/kWh** (CEA India grid average 2023)

Scope: **2** (purchased electricity, location-based)

### Travel
Format modelled on SAP Concur expense export. Distance derived from airport code lookup for routes where `distance_km` is not populated. Business class applies 2× economy emission factor per DEFRA 2023 methodology.

Emission factors (DEFRA 2023):
- Flight economy: 0.255 kgCO₂e/km
- Flight business: 0.510 kgCO₂e/km
- Hotel: 31.2 kgCO₂e/night
- Ground (taxi/rideshare): 3.5 kgCO₂e/trip
- Ground (rail): 1.2 kgCO₂e/trip
- Ground (car rental): 8.0 kgCO₂e/trip

Scope: **3** (business travel, Category 6)

---

## Suspicious flag logic

Rows are automatically flagged during ingestion. The flag is written to `suspicious_reason` so analysts can see exactly why a row was flagged, not just that it was.

Current rules:
- SAP: negative quantity (goods return/reversal), quantity > 20,000 litres
- Utility: meter reading arithmetic mismatch (current − previous ≠ consumption), duplicate meter+period, consumption > 15,000 kWh on a non-data-centre meter
- Travel: long-haul business class flight (> 5,000 km) flagged for approval visibility, not necessarily an error

---

## Known limitations

- No authentication. The `actor` field on audit log entries is null because there is no logged-in user. See TRADEOFFS.md.
- Emission factors are hardcoded in `views.py`. There is no factor versioning or recalculation when factors are updated. See TRADEOFFS.md.
- The airport distance lookup covers only the routes in the sample data. Unknown routes cause the row to fail and land in `FailedRow`. See TRADEOFFS.md.
- Ingestion is synchronous. Large files (thousands of rows) will block the request. A Celery queue would be the fix.
- SQLite in development. Switch `DATABASES` in `settings.py` to PostgreSQL before deploying.

---

## Deployment

The app is deployed at: **[your-deployed-url-here]**

Login credentials: `jyoti / admin` (if superuser was created)

Deployed on [Render].

For deployment, set these environment variables:
```
DJANGO_SECRET_KEY=your-secret-key
DEBUG=False
ALLOWED_HOSTS=your-domain.com
```

---

## Documents

- `MODEL.md` — data model design and rationale
- `DECISIONS.md` — every ambiguity resolved and what was chosen
- `TRADEOFFS.md` — three deliberate omissions and their costs
- `SOURCES.md` — per-source research findings and what would break in production
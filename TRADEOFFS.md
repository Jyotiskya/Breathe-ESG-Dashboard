# TRADEOFFS.md

Three things I deliberately did not build and why.

---

## 1. Live API integrations for SAP and travel platforms

I built CSV upload parsers instead of live integrations with SAP OData/RFC and the Concur or Navan REST APIs.

For SAP: a real integration requires RFC network connectivity to the client's SAP landscape, BASIS team involvement to create a service user, and handling of SAP's transport layer. The OData Gateway is cleaner but still requires SAP Gateway configuration and client-specific namespace setup. None of this is prototypeable without actual client credentials and network access. The CSV flat file is what a sustainability analyst actually receives from their SAP team in most organisations — it's the realistic ingestion path for this stage of a client onboarding.

For travel: Concur v4 requires OAuth 2.0 with company-level app registration. Navan requires a partnership agreement to access the API. Both would need per-client credential management, token refresh handling, and webhook infrastructure for real-time data. That's the right long-term architecture but the wrong thing to build in a four-day prototype.

The cost of this tradeoff: the system is pull-based (someone has to upload a file) rather than push-based (data arrives automatically). For a real enterprise deployment this matters — if a facilities manager forgets to export and upload the utility data for a month, it creates a gap in the reporting period. A production system would need automated extraction jobs with monitoring and alerting for missed ingestion windows.

---

## 2. An EmissionFactor model with versioning

Emission factors are hardcoded in a Python dict in views.py (`EMISSION_FACTORS`). I did not build a separate database model for emission factors with version history.

The right design would be an `EmissionFactor` table with columns for gas type, unit, factor value, applicable region, reporting year, source document, and valid-from/valid-to dates. Each `EmissionRecord` would foreign-key to the specific factor version used at calculation time. When DEFRA publishes updated factors each year, you could re-calculate historical records under the new factors and show the delta.

I didn't build this because it's a meaningful amount of schema and UI work — you need a way to load new factor versions, a way to trigger recalculation, and a way to surface the "calculated under 2022 factors, updated under 2023 factors" distinction to analysts. The current approach of storing `emission_factor` and `emission_factor_source` as flat fields on each record preserves the audit trail (you can see what factor was used) but loses the ability to recalculate in bulk when factors change.

The cost: if DEFRA revises a factor and the client needs to restate their figures, someone would need to manually update records rather than triggering a recalculation job. For a GHG inventory that goes to an auditor, factor versioning is a real requirement. This is the thing I'd build first in the next iteration.

---

## 3. Authentication and role-based access

The system has no login. Any request to the API is accepted without credentials. The `reviewed_by` and `actor` fields on `EmissionRecord` and `AuditLog` accept null, and nothing enforces that only authorised users can approve records.

A production ESG system needs at minimum two roles: data ingester (can upload files, cannot approve) and analyst (can review and approve, cannot upload on behalf of a client). Some deployments also need a read-only auditor role that can view approved records and their audit trail but cannot modify anything.

I didn't build this for two reasons. First, the assignment's stated priority is data model quality and decision-making, not user management infrastructure. Second, adding auth correctly — session management, token refresh, role enforcement on every endpoint, the frontend login flow — is a day of work that would displace time from the parts being evaluated. Django's built-in auth system and DRF's permission classes are the right tools; wiring them up is not architecturally interesting, just time-consuming.

The cost is real: without auth, the audit log is incomplete. The `actor` on every approved/rejected record is null rather than a named analyst. For a submission to an auditor, you want to be able to say "this record was approved by [name] on [date]" — right now you can only say "this record was approved on [date]." That's a genuine gap, not just a missing feature.

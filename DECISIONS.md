# DECISIONS.md

Every ambiguity I resolved, what I chose, why, and what I'd ask the PM if I could.

---

## SAP: Which export format?

SAP exposes data in several ways — IDocs over ALE, OData services via SAP Gateway, BAPIs called over RFC, or plain flat files dumped by background jobs. I chose the flat file (MM60 / ME2M style procurement export) for three reasons.

First, it's the most common thing a sustainability lead actually gets. Real SAP integrations require BASIS team involvement, RFC credentials, and network connectivity to the SAP landscape. What typically lands in an analyst's inbox is a CSV exported by the procurement team from transaction ME2M or a scheduled background job. Second, the flat file format is the hardest to parse correctly — German column headers, YYYYMMDD dates, plant codes that mean nothing without a lookup table, mixed units (L, KG, GAL, T depending on regional config). Handling this realistically demonstrates more understanding than hitting a clean OData endpoint. Third, an OData integration would require mocking a full SAP Gateway, which is out of scope.

What I chose to handle: fuel and lubricant procurement lines (DIESEL-001, PETROL-002, LPG-003, HFO-004). I mapped material codes to fuel types via a lookup table in the parser because in real SAP deployments the MATNR field contains plant-specific codes that have no intrinsic meaning — you need a separate material master extract to decode them.

What I ignored: procurement of non-fuel materials (office supplies, raw materials), goods returns/reversals beyond flagging them as suspicious, cost centre hierarchies, multi-currency amounts. A reversal in SAP generates a negative MENGE — I flag these rather than silently dropping them because an auditor needs to know a correction happened.

What I'd ask the PM: Does the client use a single SAP client or multiple (MANDT)? Are plant codes mapped somewhere we can ingest as a reference table? Are there material groups we should be pulling instead of individual material codes?

---

## Utility: Which ingestion mode?

Options were portal CSV export, PDF bill, or utility API (where available). I chose portal CSV export.

PDF bills are the realistic worst case — they require OCR or structured parsing that varies by utility provider, and the data density is low relative to the extraction complexity. They're worth building eventually but the wrong starting point for a prototype. Utility APIs exist in some markets (Green Button in the US, some BESCOM/Tata Power portals in India) but they're inconsistent, require provider-specific OAuth, and many enterprise clients don't have API access enabled on their accounts. The portal CSV is what facilities teams actually download and email around — it's the modal case.

The specific format I modelled is a multi-meter export similar to what BESCOM's commercial portal generates: meter ID, site name, billing period start/end, previous and current readings, consumption, unit, and tariff code. I kept both the raw reading values and the derived consumption figure because the parser validates them against each other (current − previous should equal consumption within rounding tolerance). A mismatch flags the row as suspicious.

What I chose to handle: kWh and MWh consumption, billing period alignment to calendar dates, duplicate meter-period detection, basic spike detection for non-data-centre meters.

What I ignored: demand charges and reactive power (kVAR), time-of-use tariff breakdown, transmission and distribution loss factors, renewable energy certificates. In a real deployment the tariff structure matters for Scope 2 market-based accounting, but that's a layer above what this prototype covers.

What I'd ask the PM: Are clients uploading one file per site or consolidated multi-site exports? Do they have access to interval (15-min) data or only monthly billing? Are any sites on green tariffs that would affect the Scope 2 emission factor?

---

## Travel: Which platform and format?

I looked at the Concur Travel API (SAP Concur) and Navan. Both expose trip data via REST APIs with OAuth 2.0. The Concur API returns itinerary objects with segment-level detail — origin, destination, cabin class, booking reference. Navan is similar but with a cleaner schema.

I chose CSV export rather than live API pull for the same reason as SAP: a prototype that requires OAuth credentials for a specific travel platform isn't reviewable by anyone who doesn't have those credentials. The CSV format I modelled reflects what a Concur expense export actually looks like — trip ID, employee ID, department, travel category, origin/destination as IATA codes, cabin class, distance where available, nights for hotels, vendor name.

The most important design decision here was handling missing distances. Concur and Navan don't always populate distance — they give you airport codes and you're expected to derive distance yourself. I built a lookup table of the routes in the sample data and raise a parse error for unknown routes, which is the honest behaviour. A production system would call an IATA great-circle distance API.

I also handle the cabin class multiplier explicitly. Business class has roughly double the emission factor of economy on long-haul routes under DEFRA methodology, because the seat occupies more floor space and is allocated a higher share of fuel burn. This isn't cosmetic — it changes the CO₂e figure materially.

What I chose to handle: flights (with distance derivation and cabin class), hotels (nights × per-night factor), ground transport (taxi, rail, car rental as flat per-trip estimates since distances aren't reliably available).

What I ignored: connecting flights as separate segments vs. a single itinerary entry, personal car mileage claims, taxi distances, freight forwarding. Hotel emission factors are rough averages — in reality they vary significantly by country and star rating.

What I'd ask the PM: Does the client use Concur or Navan specifically? Do they have a travel policy that limits cabin class above certain route lengths? Are hotel bookings tracked per property or just per city?

---

## Scope assignment

I assigned scopes at ingest time based on source and category:

- SAP fuel combustion → Scope 1 (direct emissions from owned/controlled sources)
- Utility electricity → Scope 2 (indirect from purchased electricity)
- Business travel → Scope 3 (indirect from employee travel in assets not owned by the company)

This is straightforward for the three sources in scope. It gets complicated in reality — if a client owns the vehicles in their fleet, ground transport is Scope 1, not Scope 3. I'd flag this as an assumption to validate with the client.

---

## Emission factors

I used DEFRA 2023 conversion factors for fuel and travel, and the CEA India grid emission factor (0.708 kgCO₂e/kWh) for electricity. I stored the factor and its source on each record at calculation time rather than referencing a separate table, because if DEFRA publishes a revised factor next year I want to be able to show auditors exactly what factor was used when a specific record was approved, without the factor table changing underneath historical records.

---

## Partial ingestion on failure

When a row fails to parse, I write it to a FailedRow table rather than rejecting the whole file. A file with 200 rows where 3 have malformed dates should not block the other 197 from being reviewed. The analyst dashboard can show failed rows alongside pending ones. This was a deliberate choice — I'd want to confirm it with the PM because some audit frameworks require all-or-nothing ingestion per submission.

---

## What I would ask the PM before building further

1. Is there a master list of plant codes, cost centres, and material groups we can ingest as reference data, or do we maintain the lookup table manually?
2. What happens when a client re-uploads a corrected file for a period that already has approved records? Do we re-open approved rows, create a new version, or reject the re-upload?
3. Are there any clients on market-based Scope 2 accounting (using supplier-specific emission factors or RECs) or are all clients using location-based?
4. Who plays the analyst role — internal Breathe staff, or does the client's sustainability team log in and review their own data?
5. What's the expected data volume per client per month? Synchronous ingestion is fine for hundreds of rows but will break at tens of thousands.

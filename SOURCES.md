# SOURCES.md

For each source: what real-world format I researched, what I learned, what the sample data looks like and why, and what would break in a real deployment.

---

## SAP — Fuel and Procurement

**What I researched**

SAP MM (Materials Management) is the module that handles procurement. I looked at the transaction codes ME2M (purchase orders by material) and MB51 (material document list) which are the two most common exports a procurement team would run to extract fuel consumption. I also read about IDocs (the SAP document exchange format used for EDI integrations) and the SAP OData Gateway.

The key thing I learned is that SAP flat file exports are not standardised across clients. The column headers depend on the SAP language setting — a client whose SAP system is configured in German will get `MENGE` (quantity), `MEINS` (unit of measure), `BUDAT` (posting date), `MAKTX` (material description), `WERKS` (plant). An English-configured system will get `Quantity`, `UoM`, `Posting Date`, and so on. The same client can have mixed configurations across plants if they've acquired subsidiaries.

Dates come out in YYYYMMDD format (SAP's internal date format), not ISO 8601. Units are SAP's internal unit codes: `L` for litres, `KG` for kilograms, `GAL` for US gallons, `T` for metric tonnes. Plant codes (`PL01`, `PL02`) are arbitrary identifiers that mean nothing without the plant master data.

**What the sample data looks like and why**

The headers in `sap_data.csv` are German (`MANDT`, `BUKRS`, `WERKS`, `MATNR`, `MAKTX`, `BUDAT`, `MENGE`, `MEINS`, `KOSTL`, `BELNR`, `LIFNR`) because that reflects the harder realistic case. Dates are in YYYYMMDD. I included:

- Multiple plant codes (PL01, PL02, PL03) to show the lookup problem
- Mixed units (L for liquid fuels, KG for LPG) to force unit handling
- A row with quantity 99999.000 L — an obvious data entry error or a test record that slipped through
- A row with quantity -200.000 L — a goods return/reversal, which SAP generates legitimately when a delivery is returned to the vendor. This should be flagged, not silently dropped.
- Four material codes mapping to diesel, petrol, LPG, and heavy fuel oil

**What would break in a real deployment**

The material code lookup table (`SAP_MATERIAL_MAP` in views.py) is hardcoded. Every client will have different MATNR values for the same fuel types. Before ingesting a new client's SAP data you'd need to extract their material master (transaction MM60 or a BAPI call) and build a client-specific mapping. Without this the parser raises an error for every unknown code.

Date parsing assumes YYYYMMDD. Some SAP configurations export `DD.MM.YYYY` (common in European systems). The parser would fail silently or crash on these.

Column names are assumed to be German. An English-configured SAP client would have completely different headers and the parser would fail at the column validation step.

There's no handling of multi-currency amounts. The procurement value (`DMBTR`) is in local currency. For a client with plants in multiple countries, normalising procurement cost is a separate problem.

---

## Utility — Electricity

**What I researched**

I looked at how large Indian enterprises typically get their electricity consumption data. The main sources are BESCOM (Bangalore), Tata Power and Adani Electricity (Mumbai), and MSEDCL (Maharashtra). All three have commercial customer portals that allow CSV export of billing history.

The exports typically include meter ID, site name, billing period, previous and current meter readings, derived consumption, unit (always kWh or MWh at this level), tariff code, supply voltage, and account number. The billing period is critical and often misunderstood: billing periods don't align with calendar months. A bill might cover 28 days or 33 days depending on when the meter reader visited. This means you cannot naively sum monthly consumption figures — the periods overlap or have gaps.

I also looked at the Green Button standard (used in the US) and the ESPI API format, but these aren't relevant for Indian utilities at the moment.

For Scope 2 accounting: India uses location-based accounting with a national grid emission factor published annually by the Central Electricity Authority (CEA). The 2023 figure is 0.708 kgCO₂e/kWh. There is no well-established market-based mechanism in India (no supplier-specific emission factors or I-REC market comparable to European GOs), so all Scope 2 records use the CEA factor.

**What the sample data looks like and why**

`utility_data.csv` has five meters across three sites: Bangalore HQ main building, data centre, cafeteria, Mumbai office, and Bangalore warehouse. I included:

- Both previous and current readings alongside consumption, so the parser can validate the arithmetic
- Billing periods that end at different dates (not all month-end) to reflect reality
- A data centre meter (MTR-BLR-002) with much higher consumption (~5,300 kWh/month) than the office meters (~2,000–3,500 kWh/month), which reflects real data centre power density
- A duplicate row for MTR-MUM-001 in February — same meter, same period, appearing twice — to test duplicate detection
- A spike row for MTR-BLR-002 in March showing 20,065 kWh against its normal ~5,300 kWh — flagged as suspicious by the spike detection logic

**What would break in a real deployment**

The duplicate detection checks for exact meter ID + period start + period end matches. A real utility portal sometimes exports overlapping periods with slightly different dates (e.g., one bill ends March 31 and the next starts March 31, creating a one-day overlap). The current logic would miss this.

The spike detector flags consumption above 15,000 kWh for non-data-centre meters. "Data centre" is detected by checking if the string "data" appears in the site name. That's fragile — a site called "Data Analytics Office" would be treated as a data centre. This needs a proper site classification field.

The CEA grid factor is hardcoded as a single national average. In reality different states have different grid mixes and some clients will have on-site solar generation that should be deducted. This is a known simplification.

There's no handling of kVA demand charges, power factor penalties, or time-of-use tariff breakdowns. These are in the bill but not relevant for CO₂e calculation.

---

## Corporate Travel — Flights, Hotels, Ground Transport

**What I researched**

I read the SAP Concur Travel API documentation (v4 itinerary API) and looked at Navan's export format. Both platforms expose trip data with segment-level detail — each flight leg, each hotel stay, each ground booking is a separate record with its own booking reference, origin/destination, dates, and cost.

The key finding: distance is not always populated. Concur and Navan calculate distance for some segments (usually domestic flights where they have route data) but leave it blank for others. The ICAO standard for flight emission calculations uses great-circle distance with a route inefficiency uplift factor (typically 1.08x to account for non-direct routing). For the prototype I built a lookup table of the specific routes in the sample data. A production system would call an IATA API or use the `airportsdata` Python library.

Cabin class has a large effect on emissions. DEFRA methodology assigns economy, premium economy, business, and first class different emission factors because each class occupies different floor space and gets allocated a proportional share of the aircraft's fuel burn. Business class on a long-haul flight is roughly 2.9x economy (DEFRA 2023 figures: 0.255 vs 0.510 kgCO₂e/km for long-haul). This is not a cosmetic difference — a single business class flight BLR→JFK emits more CO₂e than several months of office electricity for the same employee.

For hotels I used the DEFRA average of 31.2 kgCO₂e per room-night. This is a very rough average — actual hotel emissions vary enormously by location, star rating, and whether the hotel has its own renewables. It's the standard methodology for Scope 3 Category 6 reporting when property-level data isn't available.

**What the sample data looks like and why**

`travel_data.csv` covers January–March 2024 with 30 trip records across 8 employees. I included:

- Flights with blank `distance_km` (most international routes) to force the distance lookup to run
- Flights with populated `distance_km` (short domestic routes like BLR→BOM, BLR→HYD) where Concur would typically calculate the distance
- Both economy and business class bookings, including the high-emitter BLR→JFK business class (TRP-2024-0010, ~6,988 kgCO₂e) which gets flagged
- Hotel records with nights derived from the booking dates rather than an explicit nights column, to test the date arithmetic fallback
- All four ground categories (taxi, rail, car rental, rideshare) to exercise all emission factor lookups
- Mixed departments (Engineering, Sales, Finance, HR) to reflect realistic travel patterns

**What would break in a real deployment**

The airport distance lookup is a hardcoded dict of 20 route pairs. Any route not in that dict causes the row to fail. The fix is to integrate the `airportsdata` library and compute great-circle distance from coordinates, plus apply the ICAO 1.08x uplift factor for routing inefficiency.

Ground transport uses flat per-trip emission estimates because actual distances for taxis and car rentals aren't reliably available in booking data. For high-mileage ground transport (long car rental trips, intercity taxis) this significantly underestimates emissions. The right fix is to require distance or duration data, but that would require the travel platform to provide it.

Hotel emission factors are global averages. An accurate calculation would use region-specific or property-specific factors. Some hotel chains (Marriott, Hilton) publish property-level carbon intensity data through their sustainability APIs, but that's a significant integration effort.

The prototype doesn't handle multi-leg itineraries as a single trip. A BLR→LHR→JFK routing would come in as two separate flight records and be calculated separately, which is correct. But the trip budget (if the client tracks that) would need to aggregate across legs.

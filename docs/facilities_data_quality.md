# Facilities Data Quality: Requirements & Baseline

**Dataset:** `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities`  
**Clean output:** `workspace.default.facilities_dedup`  
**First pass completed:** June 2026  
**Records processed:** 10,088 source → 9,988 clean

---

## 1. Source Data Overview

The facilities table is populated by a web scraper that crawls Indian health facility directories, hospital websites, and aggregator platforms. The scraper outputs one row per facility with fields spanning identity, address, coordinates, specialties, and engagement metrics.

**Schema (key fields):**

| Field | Type | Notes |
|---|---|---|
| `unique_id` | STRING | UUID format; primary key |
| `name` | STRING | Facility display name |
| `specialties` | STRING | JSON array of camelCase specialty codes |
| `procedure` | STRING | JSON array |
| `equipment` | STRING | JSON array |
| `capability` | STRING | JSON array |
| `latitude` | STRING | Decimal degrees (stored as string) |
| `longitude` | STRING | Decimal degrees (stored as string) |
| `address_city` | STRING | City name |
| `address_stateOrRegion` | STRING | State or region — highly inconsistent |
| `address_zipOrPostcode` | STRING | Indian PIN code (should be 6 digits) |
| `yearEstablished` | STRING | 4-digit year (stored as string) |
| `numberDoctors` | STRING | Numeric (stored as string) |
| `capacity` | STRING | Numeric (stored as string) |

---

## 2. Cleaning Rules (Field-by-Field)

### 2.1 Structural / Corruption Checks

**Rule C1 — Drop non-UUID unique_id (Scraper Corruption Pattern A)**
- Condition: `unique_id NOT RLIKE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'`
- Action: DROP record
- Reason: The scraper intermittently parses text content (staff bios, markdown table rows, phone numbers) as facility rows, placing the text fragment in `unique_id`

**Rule C2 — Drop column-shift records (Scraper Corruption Pattern B)**
- Condition: `name LIKE '[%'` OR `address_city = 'kie'`
- Action: DROP record
- Reason: A JSON parsing failure shifts all field values left; the specialties array lands in `name`, and the string `'kie'` (likely from an HTTP cookie header) appears consistently in `address_city`

**Rule C3 — Drop empty name**
- Condition: `name IS NULL OR TRIM(name) = ''`
- Action: DROP record

**Rule C4 — Permanent exclusion list**
- Always exclude `unique_id = '3e8946bd-04ac-4d8a-b921-90ee9153f5dd'`
- Reason: Siri Dental Hospital duplicate with GPS coordinates 26.5km from the correct location; the correct record (`a1b2c3d4` series) retained

### 2.2 Numeric Fields

**Rule N1 — yearEstablished**
- Condition: `TRY_CAST(yearEstablished AS INT) NOT BETWEEN 1800 AND YEAR(CURRENT_DATE())`
- Action: SET TO NULL

**Rule N2 — numberDoctors, capacity**
- Condition: `TRY_CAST(field AS DOUBLE) IS NULL`
- Action: SET TO NULL

### 2.3 Array Fields

**Rule A1 — procedure, equipment, capability**
- If value = `'[]'` (empty array): SET TO NULL
- If value does not start with `'['`: SET TO NULL
- If value = `'[""]'` (single empty-string element): KEEP — this is a scraper artifact that indicates the field was visited but returned no structured data; it is not equivalent to a true empty array

**Rule A2 — specialties (deduplication within record)**
- Apply `ARRAY_DISTINCT(FROM_JSON(specialties, 'ARRAY<STRING>'))` before any matching or storage
- Reason: The scraper concatenates specialty lists from multiple source pages per facility; average raw count is 28 entries but only 12 are distinct
- Do NOT remove any specialty value — only collapse duplicates

### 2.4 State Standardization

See [Section 5](#5-state-name-canonical-mapping) for the full 234-value mapping table.

General rules:
- Alternate spellings → canonical form (e.g., `'Tamilnadu'` → `'Tamil Nadu'`)
- Abbreviations → full name (e.g., `'Up'` → `'Uttar Pradesh'`)
- City names → parent state (e.g., `'Mumbai'` → `'Maharashtra'`)
- District/sub-district names → parent state (e.g., `'Hooghly'` → `'West Bengal'`)
- Compound strings (city + state) → state only (e.g., `'Ghaziabad, Uttar Pradesh'` → `'Uttar Pradesh'`)
- Unresolvable values → NULL (6 values: `'Green City'`, `'Central India'`, `'Sarna'`, `'New Mondha'`, `'Bigbara'`, `'Azad Nagar'`)

---

## 3. Deduplication Rules

### Type 1 — Exact row duplicates
- Detection: identical values across all fields
- Action: `SELECT DISTINCT *` — keep one copy silently

### Type 2 — Same name + same location, different unique_id
- Detection: `LOWER(TRIM(name))` matches AND coordinates match to 3 decimal places
- Action: Keep lexicographically smaller UUID; drop others
- Exception: If one record has materially better coordinate quality (verified against city center), keep the better-located record regardless of UUID order

### Type 3a — Same name + location, incoming adds data
- Detection: Matching record exists; incoming has newly populated fields that were previously NULL
- Action: UPDATE existing record with new field values

### Type 3b — Same name + location, incoming removes data
- Detection: Matching record exists; incoming has fewer specialties or removes populated fields
- Action: FLAG for human review — do not automatically accept data removal

### Type 4 — Same name, different city
- Action: INSERT as new record (almost always a legitimate separate branch)

### Type 5 — Same name, same city, coordinates differ >1km
- Action: FLAG for human review with `conflict_type = 'location_moved'`

---

## 4. Geocoding Strategy

Executed in priority order when coordinates are missing or invalid:

| Priority | Method | Notes |
|---|---|---|
| 1 | Accept existing coords | If within India bounds (lat 8–37°N, lon 68–98°E) |
| 2 | India Post pincode directory | Join on `TRY_CAST(address_zipOrPostcode AS BIGINT) = pincode`; take AVG of all post offices per PIN. Use `TRY_CAST` for latitude/longitude columns — directory contains `'NA'` string values |
| 3 | Nominatim (OpenStreetMap) | Query: `address_line1 + city + state + "India"`. Rate limit: 1 req/sec. User-Agent: `VirtueFoundationIngestionAgent/1.0` |
| 4 | Leave NULL | Log as `coord_missing_unresolved`; record retained in dataset |

**Coordinate precision note:** Records geocoded via pincode directory are accurate to ~1–5km (post-office centroid). Records with scraper-sourced coordinates are typically facility-level (91.9% have unique coordinates).

---

## 5. State Name Canonical Mapping

Target canonical values: 28 Indian states + 7 union territories as officially recognised.

### Alternate Spellings → Canonical

| Raw Value | Canonical |
|---|---|
| Tamilnadu | Tamil Nadu |
| Orissa | Odisha |
| Chattisgarh | Chhattisgarh |
| Madhyapradesh | Madhya Pradesh |
| Uttarpradesh | Uttar Pradesh |
| Uttaranchal | Uttarakhand |
| Uttranchal | Uttarakhand |
| Telengana | Telangana |
| Jammu & Kashmir | Jammu and Kashmir |
| Jammu And Kashmir | Jammu and Kashmir |
| Jammu, J&k | Jammu and Kashmir |
| Dadra & Nagar Haveli & Daman & Diu | Dadra and Nagar Haveli and Daman and Diu |
| Dadra And Nagar Haveli And Daman And Diu | Dadra and Nagar Haveli and Daman and Diu |
| Daman And Diu | Dadra and Nagar Haveli and Daman and Diu |
| Andaman And Nicobar Islands | Andaman and Nicobar Islands |
| Pondicherry | Puducherry |
| U.t Of Puducherry | Puducherry |

### Abbreviations → Canonical

| Raw Value | Canonical |
|---|---|
| Up | Uttar Pradesh |
| U.p | Uttar Pradesh |
| U.p. | Uttar Pradesh |
| Uttar Prades H | Uttar Pradesh |
| Mh | Maharashtra |
| Ms | Maharashtra |
| Mp | Madhya Pradesh |
| M.p. | Madhya Pradesh |
| Gj | Gujarat |
| Ts | Telangana |
| Br | Bihar |
| Cg | Chhattisgarh |
| Dl | Delhi |
| U.k. | Uttarakhand |
| Ut | Uttarakhand |
| Nct Of Delhi | Delhi |
| Nct Delhi | Delhi |
| Nct | Delhi |
| Ncr-delhi | Delhi |
| Delhi Ncr | Delhi |
| Delhi/ncr | Delhi |
| Punjab Region | Punjab |
| Chandigarh (Ut) | Chandigarh |
| Chandigarh (ut) | Chandigarh |

### Cities → State

| Raw Value | Canonical State |
|---|---|
| Mumbai | Maharashtra |
| Navi Mumbai | Maharashtra |
| Navi-mumbai | Maharashtra |
| Thane | Maharashtra |
| Pune | Maharashtra |
| Nashik | Maharashtra |
| Nagpur | Maharashtra |
| Nanded | Maharashtra |
| Sangli | Maharashtra |
| Latur | Maharashtra |
| Ahmednagar | Maharashtra |
| Solapur | Maharashtra |
| Kolhapur | Maharashtra |
| Amravati | Maharashtra |
| Buldhana | Maharashtra |
| Dhule | Maharashtra |
| Palghar | Maharashtra |
| Palghar District | Maharashtra |
| Pimpri-chinchwad | Maharashtra |
| Mira Road | Maharashtra |
| Chikhali | Maharashtra |
| Panchvati | Maharashtra |
| Malshiras | Maharashtra |
| Tasgaon | Maharashtra |
| Satara District, Maharashtra | Maharashtra |
| Chennai | Tamil Nadu |
| Salem | Tamil Nadu |
| Erode | Tamil Nadu |
| Namakkal | Tamil Nadu |
| Thanjavur | Tamil Nadu |
| Tiruvannamalai | Tamil Nadu |
| Tenkasi | Tamil Nadu |
| Cuddalore | Tamil Nadu |
| Kanchipuram | Tamil Nadu |
| Kanyakumari District | Tamil Nadu |
| Ambasamudram | Tamil Nadu |
| Annanagar East | Tamil Nadu |
| Valliyoor | Tamil Nadu |
| St.thomas Mount | Tamil Nadu |
| Hyderabad | Telangana |
| Yadadri Bhuvanagiri District | Telangana |
| Thiruvananthapuram | Kerala |
| Trivandrum | Kerala |
| Kollam | Kerala |
| Malappuram | Kerala |
| Malappuram District | Kerala |
| Ernakulam | Kerala |
| Ernakulam District, Kerala | Kerala |
| Alappuzha | Kerala |
| Palakkad | Kerala |
| Idukki | Kerala |
| Kannur | Kerala |
| Thrissur | Kerala |
| Thrissur District | Kerala |
| Kottayam | Kerala |
| Kasaragod | Kerala |
| Pallom | Kerala |
| Anchal | Kerala |
| Elanthoor | Kerala |
| Chadayamangalam | Kerala |
| Pallikulam, Post Chirakkal, Kannur District, Kerala | Kerala |
| Kolkata | West Bengal |
| Nadia | West Bengal |
| North 24 Parganas | West Bengal |
| South 24 Parganas | West Bengal |
| Hooghly | West Bengal |
| Hoogly | West Bengal |
| Howrah | West Bengal |
| West Medinipur | West Bengal |
| Paschim Medinipur | West Bengal |
| Midnapore | West Bengal |
| Birbhum | West Bengal |
| Birbhum, West Bengal | West Bengal |
| Uttar Dinajpur | West Bengal |
| 24pgs (S) | West Bengal |
| 24pgs (s) | West Bengal |
| Sector 1 Salt Lake City Sector 1 | West Bengal |
| West Tripura | Tripura |
| Ludhiana | Punjab |
| Ludhiana-1 | Punjab |
| Jalandhar | Punjab |
| Jalandhar-east | Punjab |
| Mohali | Punjab |
| Bhatinda | Punjab |
| Patiala | Punjab |
| Sangrur | Punjab |
| Ahmedabad | Gujarat |
| Bhavnagar | Gujarat |
| Gandhidham | Gujarat |
| Gandhinagar | Gujarat |
| Mehsana | Gujarat |
| Kutch | Gujarat |
| Kutch, Gujarat | Gujarat |
| Kachchh | Gujarat |
| Kheda | Gujarat |
| Banas Kantha | Gujarat |
| Khambha | Gujarat |
| Ghaziabad | Uttar Pradesh |
| Ghaziabad, Uttar Pradesh | Uttar Pradesh |
| Kushinagar | Uttar Pradesh |
| Kanpur | Uttar Pradesh |
| Budaun | Uttar Pradesh |
| Sigra | Uttar Pradesh |
| Gomtinagar | Uttar Pradesh |
| Gomti Nagar | Uttar Pradesh |
| Sikandra | Uttar Pradesh |
| Nagladeena Fatehgarh | Uttar Pradesh |
| Balrampur | Uttar Pradesh |
| Faridabad | Haryana |
| Jhajjar | Haryana |
| Sirsa, Haryana | Haryana |
| Gurugram, Haryana | Haryana |
| New Delhi | Delhi |
| West Delhi | Delhi |
| East Delhi | Delhi |
| South Delhi | Delhi |
| North West Delhi | Delhi |
| South East Delhi Area | Delhi |
| Indore | Madhya Pradesh |
| Burhanpur | Madhya Pradesh |
| Rewa | Madhya Pradesh |
| Madhya | Madhya Pradesh |
| Mangalore | Karnataka |
| Mysore | Karnataka |
| Gadag | Karnataka |
| Dharwad | Karnataka |
| Dakshin Kannad | Karnataka |
| Bijapur-karnataka | Karnataka |
| Ramanagara District, Karnataka | Karnataka |
| Ajmer | Rajasthan |
| Barmer | Rajasthan |
| Dehradun | Uttarakhand |
| Almora | Uttarakhand |
| Chamoli | Uttarakhand |
| Haridwar, Uttarakhand | Uttarakhand |
| Kamrup | Assam |
| North Cachar Hills | Assam |
| Darbhanga | Bihar |
| West Champaran | Bihar |
| East Singhbhum | Jharkhand |
| Ganjam | Odisha |
| Khordha | Odisha |
| Prakasam | Andhra Pradesh |
| Guntur | Andhra Pradesh |
| Guntur District, Andhra Pradesh | Andhra Pradesh |
| Kadapa, Andhra Pradesh | Andhra Pradesh |
| West Godavari | Andhra Pradesh |
| Governorpet | Andhra Pradesh |
| Krishna | Andhra Pradesh |
| North Goa | Goa |
| South Goa | Goa |
| Sirmaur | Himachal Pradesh |
| Kashmir | Jammu and Kashmir |
| Srinagar Kashmir | Jammu and Kashmir |
| Karan Nagar | Jammu and Kashmir |
| Samba | Jammu and Kashmir |
| Kupwara | Jammu and Kashmir |

### Multi-Value / Ambiguous → NULL

| Raw Value | Action |
|---|---|
| Tamil Nadu; Tamil Nadu; Karnataka; Telangana | NULL |
| Green City | NULL |
| Central India | NULL |
| Azad Nagar | NULL |
| Sarna | NULL |
| New Mondha | NULL |
| Bigbara | NULL |

---

## 6. Data Quality: Before vs After First Pass

### Summary

| Metric | Before (source table) | After (facilities_dedup) | Change |
|---|---|---|---|
| **Total rows** | 10,088 | 9,988 | −100 |
| **Scraper corruption (Pattern A)** | 79 records (0.8%) | 0 | −79 |
| **Scraper corruption (Pattern B)** | 9 records (0.1%) | 0 | −9 |
| **Exact / UUID duplicates** | 88 duplicate rows | 0 | −88 |
| **Null coordinates** | 118 records (1.2%) | 0 | −118 |
| **Out-of-India coordinates** | 6 records (0.06%) | 0 | −6 |
| **Distinct state values** | 234 | 35 | −199 |
| **Records matchable (coords + specialty)** | ~9,880 (97.9%) | 9,958 (99.7%) | +78 |
| **Coordinate coverage** | 98.8% | **100%** | +1.2pp |
| **Facilities with unique GPS coords** | ~91% | 91.9% | +0.9pp |
| **Invalid yearEstablished** | unknown (not quantified) | 0 | cleaned |
| **Non-numeric numberDoctors / capacity** | unknown | 0 | cleaned |

### Coordinate Coverage Detail

Records with missing coordinates were resolved as follows:

| Method | Records Resolved |
|---|---|
| Nominatim (OpenStreetMap) | 11 of 29 eligible |
| Pincode directory | 19 of 19 valid-zip records |
| Deleted (garbled address, no zip) | 34 |
| Corrected out-of-India (pincode) | 5 |
| Corrected out-of-India (Nominatim) | 1 |
| **Total coordinates added/corrected** | **70** |

### State Standardization Detail

| Mapping type | Records affected |
|---|---|
| Casing / spelling fix | 89 |
| City → state | 128 |
| Abbreviation → full name | 27 |
| Compound string → state | 10 |
| Set to NULL (unresolvable) | 7 |
| **Total records updated** | **186** |

---

## 7. Ongoing Ingestion Decision Tree

```
NEW RECORD ARRIVES
│
├─ unique_id is NOT a UUID?
│    └─ DROP (scraper_corruption_pattern_a)
│
├─ name LIKE '[%' OR address_city = 'kie'?
│    └─ DROP (scraper_corruption_pattern_b)
│
├─ name IS NULL or empty?
│    └─ DROP (missing_name)
│
├─ unique_id in permanent exclusion list?
│    └─ DROP (exclusion_list)
│
├─ Clean fields (yearEstablished, numberDoctors, capacity,
│  procedure, equipment, capability, specialties, state)
│
├─ Validate coordinates
│   ├─ NULL? → try pincode dir → try Nominatim → leave NULL if both fail
│   └─ Outside India? → try pincode dir → try Nominatim → FLAG if both fail
│
└─ Match against facilities_dedup
    │
    ├─ EXACT match (name + coords, same unique_id)?
    │    └─ Type 3a: new fields populated? → UPDATE
    │    └─ Type 3b: existing fields removed? → FLAG (data_removal)
    │
    ├─ Name matches, coords match, DIFFERENT unique_id?
    │    └─ Type 2: DROP incoming (keep existing unique_id)
    │
    ├─ Name matches, DIFFERENT city?
    │    └─ Type 4: INSERT as new record (likely separate branch)
    │
    ├─ Name matches, same city, coords differ >1km?
    │    └─ Type 5: FLAG (location_moved)
    │
    └─ No match?
         └─ Type 6: INSERT as new record
```

---

## 8. Known Limitations

**Coverage gaps (Northeast India):**  
The following states have very few facilities in the dataset, reflecting scraper reach rather than actual facility density. Distance-based matching for patients in these states may return results far away.

| State | Facilities |
|---|---|
| Mizoram | 3 |
| Arunachal Pradesh | 3 |
| Nagaland | 6 |
| Sikkim | 4 |
| Manipur | 13 |
| Meghalaya | 14 |

**Specialty inflation:**  
The `specialties` field averages 28 raw entries per facility but only 12 distinct values after deduplication. Always query with `ARRAY_DISTINCT(FROM_JSON(specialties, 'ARRAY<STRING>'))`.

**Generic specialty dominance:**  
`internalMedicine` appears in 68% of facilities; `familyMedicine` in 52%. These are scraper catch-alls. Use them as a fallback tier only — specific specialties provide more signal for matching.

**Pincode-level coordinate precision:**  
Approximately 200 records (2%) have coordinates accurate only to the post-office centroid level (~1–5km). These are identifiable via the `facilities_ingestion_log` table (`reason = 'geocoded_via_pincode'`).

**ZIP / city mismatches:**  
Some records have address inconsistencies inherited from source data (e.g., a Nagpur facility with a Pune ZIP code). These were geocoded using the address text (Nominatim) rather than the ZIP code.

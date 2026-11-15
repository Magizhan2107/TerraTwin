# Cloud-first Earth thermal availability pilot v1

This implementation is isolated from the application. It aggregates MODIS
observations on Earth Engine and exports **13 period summaries**, not a raw
pixel-date table. No thermal scoring, planetary comparison or frontend wiring
is included. All scientific settings remain provisional and unchanged.

## Architectural reference: what is actually in Rover Mobility

The inspected repository contains **no Rover Mobility Earth Engine extraction
script or notebook**. Its upstream GEE job cannot be verified here. Do not
mistake the thermal pilot's scripts for Rover processing code.

The verifiable flow is:

1. Precomputed terrain measurements are stored in `public/data/`: Earth
   harmonized GeoJSON (NASA SRTM), Mars/Moon JSON (MOLA/LOLA). They carry source,
   processing, radius/grid and quality metadata, with acknowledged gaps.
2. `src/config/datasets.ts` supplies static paths.
3. `src/services/datasets.ts` fetches, caches, parses and validates records,
   preserving metadata. Earth has 735 source records, 731 accepted candidates.
4. `src/modules/roverMobility/scoring.ts` computes terrain scores **in the
   browser**, not in Earth Engine. `src/modules/roverMobility/index.ts` exposes
   its independent scientific-module adapter.
5. `src/pages/App.tsx` consumes those results for maps, charts and JSON exports.

Reusable patterns: precompute expensive geospatial measurements; publish
versioned static artifacts; validate before use; join by canonical ID; retain
provenance; keep domain processing separate from UI. No terrain formulas,
terrain resampling, or browser-side thermal aggregation are copied. Thermal
uses its independently validated native MODIS/time/mask definitions.

## Implementation

- `cloud_rules.py`: derives QA lookup tables and time lookup tables from
  existing `common.py` functions. Even the valid LST interval is derived from
  the existing classifier over the uint16 storage domain. No scientific
  thresholds are maintained separately. Masked payloads remain sentinel
  values; zero QA cannot be imputed from an absent source mask.
- `cloud_aggregate.py`: constructs deferred server-side processing for one
  location/year. It performs per-band availability, valid LST, QC, QA, time,
  date and period aggregation inside EE. Calling the builder never evaluates
  a graph or starts a task.
- `cloud_contract.py` and `cloud.diagnostic.schema.json`: versioned compact
  schema, provenance hashes, format conversion and semantic validation.
- `cloud_compare.py`: compares compact output to the preserved offline report
  and, for fields absent from that report, the existing raw validation CSV.
  Raw processing here is a **test oracle**, not the cloud production path.
- `cloud_pilot.py`: offline planning/conversion/comparison; explicit single-job
  submission and read-only status monitoring. There is no batch-submit command.
- `tests/test_cloud.py`: synthetic scientific-rule, mask, counting, contract,
  provenance, comparator and real-API graph-serialization regressions.

Existing scripts, config, datasets, reports, investigations and task manifests
have not been changed. Use the existing pilot `.venv`; no new dependencies.

## Cloud computation and exact sampling semantics

The configured MYD11A1 collection/date bounds, canonical coordinates, geodesic
radius, geometry error, tile scale and thresholds are read from the existing
configuration. The native projection comes from the same first LST_Day image
as the raw exporter. No nominal 1000 m scale, best-effort resolution change,
bilinear resampling or random sampling is used.

All spatial sums use `ee.Reducer.sum().unweighted()` and the explicit native
projection, with **no scale override**. Unweighted reducers include pixels by
their centres; weighted sums would change boundary inclusion. This matches
the validated centre-based raw sample inclusion rule. The centre count and
summed native area are computed once. The full footprint area is also retained.
Boundary-area support remains the existing whole-centre-cell approximation,
not exact polygon/pixel intersection.

No new x/y rounding is needed: contributing-centre unions operate directly on
aligned raster cells. This preserves native identities without flooring or
Python ties-to-even rounding of half-integer coordinates.

Each image becomes a fully unmasked Boolean diagnostic raster. Presence flags
come from each source band's own mask. LST validity and QA/time membership use
the established classifier lookup definitions. Missing QC never qualifies.
Each date is spatially reduced once for per-stage pixel counts, any-hit flags,
strict native-area support and joint day/night strict-window support.
Period reductions sum date flags and pixel counts. A temporal raster sum >0
followed by a spatial count computes distinct contributing centres; it is not
a sum of monthly unique-centre counts. Empty source periods have a zero raster
seed with the correct bands/projection. A known source-empty period can have
zero counts; an unprocessed period cannot.

Each month's daily columns are summed together with one repeated sum reducer,
rather than one remote request per statistic. The yearly record is computed
from the same year's date/raster sets and must reconcile with the twelve
months. Duplicate product dates or image IDs produce explicit failure records,
not double-counted observations. Status validation never equates a nonzero
count or a passed exploratory screen with scientific suitability.

References: [EE reduceRegion](https://developers.google.com/earth-engine/apidocs/ee-image-reduceregion),
[weighted versus unweighted reductions](https://developers.google.com/earth-engine/guides/reducers_weighting),
[Drive table export](https://developers.google.com/earth-engine/apidocs/export-table-todrive).

## Versioned output contract

Version: `earth-thermal-cloud/1.0.0`; pipeline `native-centre-cloud/1.0.0`.

Transport: one Drive GeoJSON FeatureCollection with 13 null-geometry features.
Each feature is an aggregated period, never a satellite pixel observation.
GeoJSON preserves numeric types and flat property names without CSV parsing
or fragile nested-JSON string fields. Offline `convert` performs validation
and formatting only, producing a static JSON envelope:

```json
{
  "schema_version": "earth-thermal-cloud/1.0.0",
  "configuration": { "...": "exact existing pilot config" },
  "script_sha256": { "...": "submission-pinned script hashes" },
  "records": ["12 monthly objects and one yearly object"]
}
```

This is a **structural illustration**, not a complete schema-valid artifact.
The exhaustive machine-validatable contract is `cloud.diagnostic.schema.json`.
The following **synthetic field excerpt** illustrates units, not observations:

```json
{
  "location_id": "24",
  "period": "2021-01",
  "native_centres": 2,
  "source_product_dates": 1,
  "pixel_date_records": 2,
  "night__lst_valid__pixels": 2,
  "night__qc_missing__pixels": 1,
  "night__qc_present__pixels": 1,
  "night__strict_qa_in_phase__dates": 0,
  "night__strict_qa_in_phase__centres": 0,
  "night__strict_qa_in_phase__calendar_fraction": 0,
  "status": "no_eligible_observations",
  "mission_suitability": "not_assessed"
}
```

All summary fields are mandatory for completed processing; only fixed identity/
spatial/provenance metadata is allowed for `not_processed`/`processing_failure`.
Missing metrics cannot silently become zeros. The offline plan lists all 30
location/year partitions as unprocessed with null observation counts until
there is evidence of processing; it is a plan, not an observation dataset.

Field groups:

- Identity: canonical string ID/name/coordinates, Earth, month/year and run ID.
- Provenance: dataset, product version, schema/pipeline versions, catalogue and
  config SHA-256, and pipeline SHA-256 over the sorted per-script hash bundle.
  The envelope retains exact config and individual script hashes. Source image
  IDs/dates are retained as `|`-separated inventories for each period.
- Spatial: native CRS, WKT affine transform (a **string**, not a numeric list),
  radius, native centre count, sampled whole-cell area and requested area.
- Each `day__METRIC` / `night__METRIC` has `__pixels` (pixel-date retrievals),
  `__dates` (distinct UTC product dates), `__centres` (period union of native
  cells), and `__calendar_fraction` (`__dates / calendar_dates`).
- All existing `common.STAGES` are included, plus `lst_band_present`,
  `qc_band_present`, `time_band_present` (unconditional source-mask presence),
  `qc_missing` (valid LST with absent QC), `qc_valid` (alias of existing
  conditional `qc_present`), `time_missing` (valid LST with missing time), and
  `time_interpretable` (alias of conditional `time_valid`).
- Source coverage is source dates / calendar dates; `missing_product_dates` is
  the calendar count minus source dates. Joint support and per-phase supported
  dates retain the existing native-area and calendar denominators.
- `unknown_qc_present` is a 0/1 indicator. Unknown QC and strict rejection are
  distinct; neither is a reconstructed QA byte.

Status meanings:

| Status | Meaning |
| --- | --- |
| `data_available` | Both phases have strict-window dates; for a month the unchanged exploratory screen passes. Annual screening is not defined. No suitability claim. |
| `no_eligible_observations` | One or both phases have zero strict-window dates; other observations may exist and remain visible. |
| `insufficient_coverage` | Both phases have some strict-window dates but the monthly provisional screen fails. |
| `not_processed` | No observation results; summary fields absent, never zero-filled. |
| `processing_failure` | Explicit failed source validation; no observation summary fields. Task failures also remain explicit EE status/error responses. |

`coverage_screen` separately preserves the monthly below/meets-screen decision
and uses `not_evaluated_year` for annual records. `status_reason` states why.
`mission_suitability` is always `not_assessed`.

## Local verification and remaining acceptance boundary

Run only local tests:

```bash
experiments/earth_thermal_pilot/.venv/bin/python -B -m unittest discover \
  -s experiments/earth_thermal_pilot/tests -v
```

Tests exhaust all 256 QA bytes against `common.py`, both time windows and
boundaries, midnight wrapping, masked QC versus genuine QA=0, LST validity,
date/cell/pixel distinctions, monthly/yearly accounting, schema/status rules,
canonical coordinates/hashes, format-only conversion and comparator failures.
Real EE API graph checks use packaged signatures with network, server
evaluation and Task.start blocked. Synthetic fixtures never become scientific
outputs.

A single bounded read-only query evaluated **two Atacama source images**,
2021-01-01/02, covering 180 native pixel-date cells. All **135 checked counts**
(pixel/date/centre metrics plus source/native-grid totals) matched the existing
CSV. Evidence: `outputs/cloud_atacama_two_date_check_001.json`. Its January
record intentionally contains only those two source dates; it is not a real
full-month or full-year cloud result. The source-mask investigation was not
repeated.

**Full Atacama 2021 cloud-versus-offline equivalence remains unverified.**
No new export was submitted. The approved run must compare all 13 periods.
The comparator reports matching, mismatched, missing, unexpected, unverified
fields and differences in definitions; it does not adjust thresholds. The raw
CSV is used only for mask-presence fields/contributing-centre counts absent
from the old report. Empty-period area differs deliberately: the old reporter
leaves sampled area null without images; the compact format retains the
invariant grid area and validates it across periods.

## Prepared first run — DO NOT EXECUTE before approval

From the repository root, the following **offline** command prints the plan:

```bash
experiments/earth_thermal_pilot/.venv/bin/python -B \
  experiments/earth_thermal_pilot/cloud_pilot.py plan \
  --location-id 24 --year 2021 --run-id thermal_cloud_validation_001
```

After explicit approval, submit exactly **one** aggregated export:

```bash
experiments/earth_thermal_pilot/.venv/bin/python -B \
  experiments/earth_thermal_pilot/cloud_pilot.py submit \
  --project landslide-1-510217 \
  --location-id 24 --year 2021 --run-id thermal_cloud_validation_001 \
  --drive-folder TerraTwinThermalCloudPilot
```

Target: only canonical ID 24 / Atacama_3_3 / 2021. Scope is approximately
365 source images × 90 native centres = 32,850 pixel-date cells, with 13
summary records. One task writes
`tt_cloud_thermal_cloud_validation_001_24_2021.geojson` to Google Drive folder
`TerraTwinThermalCloudPilot`. Expect tens to hundreds of KB, rather than the
13 MB raw CSV (estimate). Runtime may be minutes to tens of minutes plus queue
time (estimate, not measured); quotas and graph evaluation can affect this.
No additional task or collection-wide extraction is needed for this run.
Further locations/years require separate approval; the CLI has no bulk mode.

An immutable prepared intent is written to
`outputs/cloud/tasks/thermal_cloud_validation_001_24_2021.prepared.json` before
Task.start. A separate `.submitted.json` receipt records the confirmed task ID.
No existing records are overwritten. If a start result is ambiguous, inspect
EE Tasks and the prepared intent; do not retry or reuse the run identifier.

Monitor read-only after submission:

```bash
experiments/earth_thermal_pilot/.venv/bin/python -B \
  experiments/earth_thermal_pilot/cloud_pilot.py status \
  --receipt experiments/earth_thermal_pilot/outputs/cloud/tasks/thermal_cloud_validation_001_24_2021.submitted.json
```

After completion, download **only the compact result** to a fresh path such as
`outputs/cloud/downloads/tt_cloud_thermal_cloud_validation_001_24_2021.geojson`.
No automatic downloads or new authentication are initiated by these tools.

```bash
experiments/earth_thermal_pilot/.venv/bin/python -B \
  experiments/earth_thermal_pilot/cloud_pilot.py convert \
  --input experiments/earth_thermal_pilot/outputs/cloud/downloads/tt_cloud_thermal_cloud_validation_001_24_2021.geojson \
  --manifest experiments/earth_thermal_pilot/outputs/cloud/tasks/thermal_cloud_validation_001_24_2021.submitted.json \
  --output experiments/earth_thermal_pilot/outputs/cloud/thermal_cloud_validation_001_24_2021.json

experiments/earth_thermal_pilot/.venv/bin/python -B \
  experiments/earth_thermal_pilot/cloud_pilot.py compare \
  --input experiments/earth_thermal_pilot/outputs/cloud/thermal_cloud_validation_001_24_2021.json \
  --baseline experiments/earth_thermal_pilot/outputs/availability_pilot_002.json \
  --raw-baseline experiments/earth_thermal_pilot/outputs/downloads/tt_avail_availability_pilot_002_24_2021.csv \
  --output experiments/earth_thermal_pilot/outputs/cloud/thermal_cloud_validation_001_comparison.json
```

Acceptance requires schema/semantic/provenance validation, all required fields,
zero mismatches or unverified comparison fields, 365 dates, 90 centres,
32,850 pixel-date rows, and the established nighttime counts and monthly/date
totals. A successful local synthetic comparison is not cloud equivalence.

## Scientific limitations

The observed Atacama strict-night QA zero and source QC masking remain intact.
Unknown source QC is not good or bad quality. Six earlier provenance samples
do not prove the cause for every masked byte; original NASA HDF payloads remain
unverified. Daily Level-3 retrievals are not continuous thermal monitoring,
raw swath counts, independent samples or paired hardware thermal cycles.
Clear-sky selection and mask/temporal coverage can bias later temperature
products. No new methodology, missing-value recovery or thermal scoring is
approved here. The first actual export may expose EE batch-resource limits or
source changes; these must be diagnosed without changing scientific rules.

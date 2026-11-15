# Earth thermal observation-availability pilot

Isolated MYD11A1 Collection 6.1 diagnostics for the exact ten approved canonical Earth IDs. This folder is separate from `src/`, `public/data/`, the JavaScript tests and the teammate's backend. It has no frontend hook and calculates no thermal similarity or exposure metrics.

## Execution state

Prepared locally on branch `thermal-integration`. No Earth Engine initialization, authentication, export or remote extraction has been run. No observed coverage or phase-window feasibility result is available yet.

Initial environment inspection found Python 3.14.6 at `/home/red_drago/anaconda3/bin/python3` and Python 3.12.16 at `/home/red_drago/anaconda3/envs/nasa-geo/bin/python`. Neither has `earthengine-api` or `google-auth`. The default interpreter has `jsonschema`. No standard Earth Engine user credential file or Application Default Credential file was present, and `GOOGLE_APPLICATION_CREDENTIALS` was unset. File presence does not prove usable authentication or project access. No credential contents were read.

## Files

| File | Responsibility |
| --- | --- |
| `config.json` | Exact pilot IDs, 2021–2023 period, 5 km radius, provisional windows and screening hypotheses |
| `common.py` | Read-only catalogue resolution, configuration checks, QA/time interpretation |
| `ee_export.py` | Native-grid asynchronous export graph and raw CSV columns |
| `pilot.py` | Offline planning/environment/report CLI and explicit remote `submit` command |
| `reporting.py` | Offline CSV integrity checks, counts, histograms, monthly/yearly summaries and output validation |
| `diagnostic.schema.json` | Draft 2020-12 JSON Schema for diagnostic reports |
| `QA_INTERPRETATION.md` | Band scales, fill values, QA bits, time conventions and counting limitations |
| `tests/test_pilot.py` | Offline tests using real catalogue IDs and explicitly synthetic in-memory/temporary CSV fixtures |
| `requirements.txt` | Dependencies for an approved isolated environment |
| `.gitignore` | Keeps downloaded/derived outputs, virtual environment and bytecode outside Git |

## Configuration and identity

The script reads coordinates from `public/data/earth_terrain_harmonized.geojson`, without hardcoding them. It mirrors the existing frontend terrain acceptance checks and verifies 731 accepted candidates, the exact ten IDs, and their expected names. A changed count or mismatched ID fails before remote execution. Nothing writes to this GeoJSON.

Approved pilot IDs are `24`, `73`, `122`, `220`, `269`, `318`, `367`, `465`, `661`, and `710`. IDs are strings throughout. Each export/report carries the catalogue and configuration SHA-256 hashes. A changed file causes downloaded outputs from an earlier configuration to fail validation. Run IDs also prevent accidental mixing of separate experiments.

Defaults are `[2021-01-01, 2024-01-01)` UTC, [13:00,15:00) day local solar time, [01:00,03:00) night local solar time, a geodesic 5,000 m radius, native-grid sampling, and separate strict/relaxed QA diagnostics. Phase windows and monthly thresholds remain provisional. Make a new run ID after a configuration change.

## Ubuntu commands safe to run now

```bash
cd /home/red_drago/Desktop/Desktop/Others/NASA/TerraTwin

git branch --show-current
python3 -B experiments/earth_thermal_pilot/pilot.py environment
python3 -B experiments/earth_thermal_pilot/pilot.py plan
python3 -B -m unittest discover -s experiments/earth_thermal_pilot/tests -v
```

These commands do not import or initialize Earth Engine and do not authenticate or contact it. Planning prints metadata and the 30 proposed partitions to stdout. Optional `plan --output experiments/earth_thermal_pilot/outputs/plan.json` writes only an isolated local plan. Existing output paths are never silently overwritten.

The tests use `jsonschema` for output validation. It is already available in the inspected default environment. If an alternative interpreter lacks it, report that dependency and obtain installation approval. Test CSV fixtures are temporary, visibly named synthetic, and removed automatically. They are not pilot observations.

## Setup only after installation/authentication approval

An existing Python 3.12 interpreter is available on this Ubuntu host. The following creates a separate environment inside this folder and does not install into the user's existing environments.

```bash
cd /home/red_drago/Desktop/Desktop/Others/NASA/TerraTwin

/home/red_drago/anaconda3/envs/nasa-geo/bin/python -m venv experiments/earth_thermal_pilot/.venv
experiments/earth_thermal_pilot/.venv/bin/python -m pip install -r experiments/earth_thermal_pilot/requirements.txt
experiments/earth_thermal_pilot/.venv/bin/python -B experiments/earth_thermal_pilot/pilot.py environment
experiments/earth_thermal_pilot/.venv/bin/earthengine authenticate --auth_mode=localhost
```

The chosen Google Cloud project must have Earth Engine enabled/registered, the appropriate access permissions and applicable account verification. Drive export needs authorized Drive access. Choose a unique output folder name if the account contains duplicate folder names. The pilot never calls `ee.Authenticate()` or starts an interactive login automatically. Do not put credentials in `config.json` or Git.

Package versions are resolved during the separately approved install and recorded in each submission manifest. No claim of remote compatibility is made until the first approved smoke export succeeds.

## Remote submission only after explicit extraction approval

Begin with one location/year. `submit` is the sole remote entry point. Earth Engine initialization itself may make network requests. Graph construction stays server-side; there is no `getInfo()`, `evaluate()`, bulk synchronous result transfer, or remote processing during `plan`/`report`.

Set `PILOT_GEE_PROJECT` to the approved real project ID before running the command. The example run ID is an execution label, not an observation record.

```bash
cd /home/red_drago/Desktop/Desktop/Others/NASA/TerraTwin

export PILOT_GEE_PROJECT='YOUR_APPROVED_PROJECT_ID'
experiments/earth_thermal_pilot/.venv/bin/python -B experiments/earth_thermal_pilot/pilot.py submit \
  --project "$PILOT_GEE_PROJECT" \
  --location-id 24 \
  --year 2021 \
  --run-id availability_pilot_001 \
  --drive-folder TerraTwinThermalAvailabilityPilot
```

One invocation starts one asynchronous Google Drive CSV task and writes an isolated task manifest under `outputs/tasks/`. It does not auto-submit the remaining 29 partitions or wait/poll remotely. Monitor the printed task ID in Earth Engine Tasks. Review one successful smoke export before authorizing more partitions. Repeat with each exact approved ID and year 2021, 2022 and 2023 only within the authorization granted.

A pre-existing manifest stops repeat submission for the same run/ID/year. If a request fails after task submission, the manifest can retain `start_not_yet_confirmed`. Inspect Earth Engine Tasks before retrying; a missing success message does not establish that no task was created. Do not delete manifests as an automatic retry strategy.

The first-image native projection is used across the collection. Source image IDs, dates, CRS, affine transform and expected native-cell keys are exported in the partition inventory. The `grid_transform` column retains the WKT string returned by `Projection.transform()` as opaque, nonempty metadata. If collection ingestion or projections change, investigate and version the pilot before interpreting results.

### Raw pixel coordinates and inventory keys (raw/1.0.0)

`pixel_x`/`pixel_y` come from `ee.Image.pixelCoordinates(projection)` sampled
on the native projection. In the completed Atacama 2021 export these are
pixel-centre grid coordinates `n + 0.5`, not integer cell indices. Applying
the inverse exported affine transform to the sinusoidal positions derived
from the pixel-centre longitude/latitude reproduced every coordinate within
4e-12 pixels (MODIS sinusoidal sphere radius 6371007.181 m). In particular,
`X = a*x + c`, `Y = e*y + f`, using the inventory WKT's `elt_0_0`,
`elt_0_2`, `elt_1_1`, `elt_1_2`; sinusoidal `X = R*longitude*cos(latitude)`,
`Y = R*latitude`, with angles in radians.

The exporter separately labels inventory coordinates with `format("%.0f")`.
These labels must not be interpreted as zero-based floor indices: all 90
Atacama centre pairs map one-to-one to inventory labels by positive half-up
conversion (`14090.5:13615.5` becomes `14091:13616`). Flooring fails to match
inventory; Python's ties-to-even `round()` collapses the 90 pairs to 26 keys.
Reporting keeps integer coordinates unchanged for backward compatibility;
exact half-integers map to integer labels with half ties away from zero
(`floor(v+0.5)` for positive values, `ceil(v-0.5)` for negative values).
Negative half ties are a compatibility convention, not verified by this
positive-index Atacama export. Arbitrary fractions, nonfinite/missing values,
mixed x/y lattices, and convention changes within a partition are rejected.
Complete daily key sets must still match inventory exactly, and duplicate
keys remain errors. Inventory rows intentionally have blank pixel fields
and are never passed through pixel-coordinate validation.

This corrects the offline interpretation of the existing raw/1.0.0 contract;
no export columns, raw files, grid, observation values, QA/time semantics,
counting rules, diagnostic schema version, or thresholds change. No re-export
is required. The local optional real-CSV regression test is skipped when the
Atacama download is absent.


## Offline reporting after exports have completed

Download complete CSVs from Google Drive into `experiments/earth_thermal_pilot/outputs/downloads/`. Keep one complete CSV per location/year and a single run/configuration in that directory. A normal partition is small enough for one CSV. Truncated files, duplicate downloads and manually split shards are rejected; preserve complete exports.

```bash
mkdir -p experiments/earth_thermal_pilot/outputs/downloads

# After manually downloading the approved completed exports:
experiments/earth_thermal_pilot/.venv/bin/python -B experiments/earth_thermal_pilot/pilot.py report \
  --input-dir experiments/earth_thermal_pilot/outputs/downloads \
  --run-id availability_pilot_001 \
  --output experiments/earth_thermal_pilot/outputs/availability_pilot_001.json
```

Partial imports are permitted and explicitly marked. There are always 360 monthly and 30 yearly records covering the same ten IDs. Unreceived partitions remain `pending_export` with null counts. For a completed 30-partition pilot, add `--require-complete`. Report creation is entirely local and requires no Earth Engine authentication.

## Diagnostic output schema

### Raw Drive CSV

`ee_export.py:COLUMNS` is the authoritative column order. Each file includes:

- Common identity fields, exact canonical coordinate snapshot, dataset ID, run ID, year, radius and catalogue/configuration hashes.
- One `partition_inventory` row with actual source image count, image IDs/dates, native grid cell count/keys, CRS/transform and requested geodesic area.
- `pixel` rows with source image ID and UTC product date, native pixel indices, pixel-centre coordinates, native pixel area, all ten raw bands and their individual `_present` mask flags.

The two coordinate kinds are deliberately named. Pixel centres are satellite-grid diagnostic coordinates, not replacement Earth candidate coordinates. A masked band has raw value -9999 and `_present=0`. Inventory and pixel rows use `earth-thermal-availability-raw/1.0.0`.

### Local JSON report

`diagnostic.schema.json` defines `earth-thermal-availability-report/1.0.0`. The CLI validates it with Draft 2020-12 plus semantic checks before writing. Key fields are:

| Field | Meaning |
| --- | --- |
| `received_partitions`, `expected_partitions` | Imported complete location/year exports, out of 30 |
| `export_files`, `processing_script_sha256` | Input CSV hashes and processing source fingerprints |
| `records[].period_type`, `period` | UTC product-date month or year |
| `input_status` | `complete` or `pending_export` |
| `expected_product_dates`, `source_product_dates` | Calendar opportunities and actual source dates |
| `missing_product_dates` | Dates absent from the source inventory; null when no export was received |
| `phases.*.pixel_retrieval_counts` | Daily native-cell retrieval count for each availability/QA/time stage |
| `phases.*.distinct_product_dates` | Distinct product dates with at least one cell passing each stage |
| `source_product_date_fraction`, `calendar_date_coverage_fraction`, `strict_phase_supported_calendar_date_fraction` | Explicit source-date, per-stage date and spatially supported date fractions over calendar dates |
| `qa_histograms` | Counts for all four categories of each published two-bit QA field |
| `*_observation_time_raw_dn_histogram` | Native time distributions, before QA and under strict/relaxed QA |
| `circular_mean_local_solar_hour` | Circular mean of valid product times, or null |
| `dates_with_strict_phase_support_at_threshold` | Dates with strict/in-window data covering the provisional native-centre area fraction |
| `same_product_date_joint_strict_phase` | Spatial intersection on the same product date; no physical-cycle-pair claim |
| `exploratory_screen` | Monthly comparison against explicitly provisional criteria, with failure reasons |
| `raw_swath_observation_count`, `effective_independent_observation_count` | Always null for this product-level pilot |

Yearly date and stage totals must equal their monthly sums. The validator also checks identity, count subsets, histograms, duplicates, inventories and coordinate consistency. The report never contains fabricated temperature values, thermal similarity scores or a production eligibility flag.

To assess window feasibility, compare the strict-QA time histogram against the requested intervals and inspect seasonal retention after QA. To assess provisional thresholds, inspect per-phase supported-date counts and monthly reasons. No empirical feasibility conclusion exists until exports are processed and reviewed.

## Runtime, data volume and quotas

All figures here are planning estimates, not benchmark results.

- One 5 km-radius footprint is about 78.5 km². Native-centre sampling may include roughly 70–110 grid cells; inspect actual inventory counts.
- The full 10-location, 1,095-day period is roughly 0.8–1.2 million daily grid rows plus 30 inventory rows. Each row carries both phases. This is not a raw swath-observation count.
- Expect approximately 200–800 MB of CSV, depending on cell counts, serialization and repeated metadata.
- A location/year batch might take 5–60 minutes of execution, with additional queue time. Slow tasks or queue conditions can extend to hours. The whole pilot could take several hours or longer.
- The offline report processes one export at a time. Memory scales with the largest CSV partition, while output summaries cover all locations. A few minutes and roughly 100–400 MB of local memory are reasonable estimates to verify on the first real export.
- Start with one task. Batch concurrency and EECU limits depend on the actual project/account/tier and were not queried. Earth Engine's published default quota table lists average concurrency of two batch tasks, with plan/tier-specific limits.
- `tileScale=4` reduces aggregation tile size. No `bestEffort` coarsening or spatial scale change is used. If a job hits a memory/time limit, inspect it first. A later reviewed revision could partition by month without changing the sampling grid.

References: [batch table export](https://developers.google.com/earth-engine/guides/exporting_tables), [quotas](https://developers.google.com/earth-engine/guides/usage), [authentication](https://developers.google.com/earth-engine/guides/auth), and [native-projection sampling](https://developers.google.com/earth-engine/apidocs/ee-image-sample).

## What remains unverified

The Earth Engine client is absent. Graph serialization against the actual client, project access, actual archive image/projection behavior, Drive export, runtime and measured availability have not been exercised. The graph uses documented APIs, but a successful approved smoke export is required to verify the remote path. Phase/QA feasibility and thresholds remain scientific review items.

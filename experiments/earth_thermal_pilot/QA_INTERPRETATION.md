# MYD11A1.061 availability interpretation

This is an observation-availability experiment. Phase windows and screening thresholds remain provisional. It produces no temperature similarity, ranking, thermal inertia or scoring eligibility decision.

## Authoritative references

- [Earth Engine MYD11A1.061 band catalogue](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MYD11A1)
- [MODIS Collection 6 user guide, daily LST SDS Table 8](https://lpdaac.usgs.gov/documents/118/MOD11_User_Guide_V6.pdf)
- [Collection 6.1 user guide](https://lpdaac.usgs.gov/documents/715/MOD11_User_Guide_V61.pdf)

The catalogue's linked guide is Collection 6. The C6.1 guide should also be retained with an extraction review. Product masks and actual observed encodings remain visible in the raw export. Pin and record the Earth Engine API version when remote execution is authorized.

## Temperature availability and masks

`LST_Day_1km` and `LST_Night_1km` are uint16. The daily SDS guide specifies raw valid values 7500–65535, fill 0, and Kelvin = raw × 0.02. The catalogue currently prints an inconsistent nighttime upper bound of 65635. The pilot uses the uint16/guide upper bound of 65535 and preserves raw encodings. It applies no additional plausible-Earth-temperature cutoff.

`lst_valid` counts unmasked, numerically valid daily grid retrievals before QA filtering. `qc_present` additionally requires an unmasked QA byte in 0–255. These are different stages. A valid-looking LST with cloud/failed QA remains in the diagnostic base count and fails the relevant QA profiles.

Bands are losslessly cast to signed int32 for export so the negative sentinel cannot wrap in unsigned storage. Their unmasked numeric values stay unchanged. Each exported band has a separate `_present` flag. A masked band is exported as -9999, with `_present=0`. This sentinel is local export representation only. It is never interpreted as a measurement or as QA=0. Published fill values remain visible when unmasked, and temperature fill 0 is rejected.

## Observation-time interpretation

`Day_view_time` and `Night_view_time` use raw values 0–240 and scale 0.1 local solar hour, a six-minute encoding step. Decode from these bands for each valid daily LST pixel. Retain raw values as well as decoded-time summaries. Do not infer acquisition time from the nominal orbit or candidate longitude.

Native values 0 and 240 both map to clock midnight for window membership. Keep them separate in raw-DN histograms. Zero is also the documented fill value. A zero time is inspected only with an unmasked valid LST, and its ambiguity is reported through `zero_time_with_valid_lst_count`. The default windows exclude midnight, so zero-time ambiguity cannot create a default phase-window hit. A future midnight-spanning experiment must review these ambiguous cases explicitly.

Intervals are start-inclusive/end-exclusive. Defaults are [13,15) for day and [1,3) for night. Circular interval logic also supports intervals such as [22,2). Do not take an ordinary arithmetic mean of times spanning midnight. The report uses a circular mean, and retains histograms for all, strict-QA, and relaxed-QA observations. The mean is null when direction is undefined or no times exist.

These bands supply the product's local-solar-time representation. This pilot does not infer apparent-versus-mean solar-time equivalence with other planetary instruments. `product_date_utc` comes from Earth Engine `system:time_start` and is the product date used for accounting. It is not asserted to be the local acquisition date or a unique raw swath date.

## Quality bit fields

Both `QC_Day` and `QC_Night` are decoded independently.

| Bits | Field | Categories |
| --- | --- | --- |
| 0–1 | Mandatory QA | 0 produced/good, 1 produced/other quality, 2 not produced/cloud, 3 not produced/other reason |
| 2–3 | Data quality | 0 good, 1 other, 2/3 TBD |
| 4–5 | Emissivity error | 0 ≤0.01, 1 ≤0.02, 2 ≤0.04, 3 >0.04 |
| 6–7 | LST error | 0 ≤1 K, 1 ≤2 K, 2 ≤3 K, 3 >3 K |

Per-field four-category histograms are reported for available LST with valid QC. The histogram bins are exclusive categories. A cumulative ≤2 K diagnostic is bins 0+1. Published error categories are not complete measurement uncertainty or standard-error estimates.

Individual criterion counts are independent tests against the same available-QC population. They are not a sequential attrition waterfall. The separate combined profiles show simultaneous criteria.

- `mandatory_produced` allows mandatory 0 or 1.
- `mandatory_good` requires mandatory 0.
- `data_quality_good` requires data-quality 0.
- `emissivity_error_le_0_01` requires emissivity category 0.
- `lst_error_le_1k` requires LST-error category 0.
- `strict_qa` requires all four categories to be 0.
- `relaxed_qa` allows mandatory 0/1, data quality 0, emissivity 0/1 and LST error 0/1.
- `_with_time` also requires a valid observation-time encoding.
- `_in_phase` adds membership in the configured phase window.

Strict and relaxed are exploratory labels. Neither profile is automatically approved for future thermal scoring.

View angles and clear-sky coverage bands are preserved for inspection, without adding an unapproved angle or coverage threshold. View-angle raw range is 0–130 with offset −65 degrees and fill 255. Clear-sky coverage uses scale 0.0005, but it must not be mistaken for the geometric fraction of TerraTwin's circular footprint.

## Counting units and spatial support

A daily native-grid pixel can contain more than one qualifying source observation, especially above 30° latitude. The pilot reports daily Level-3 pixel-retrieval counts, distinct UTC product dates, and native spatial cells separately. Raw swath counts and effective independent observation counts stay null. A different product or additional processing would be needed to establish those quantities. Distinct product dates are sampling opportunities, without an assumption of statistical independence.

The Earth Engine batch graph samples all pixel centres inside a geodesic 5,000 m-radius buffer on the collection's native LST projection. No 1000 m scale override, upsampling, random subsampling, or bilinear interpolation is applied. Native cell indices, pixel-centre coordinates, masks and pixel areas are exported. Candidate coordinates remain the unrounded catalogue values.

Spatial support is an estimate on the native-centre grid. For each date and mask, it is supported native-cell area divided by all sampled native-cell area. Boundary pixels are included by their centres; exact clipped-cell overlap is not computed. Both sampled-centre area and the requested geodesic-circle area are reported to expose boundary approximation. Nominal 1 km sampling does not establish a 1 km effective footprint or independent pixels.

`same_product_date_joint_strict_phase` is the spatial intersection of day/night strict-phase masks within the same daily product. This does not prove a paired physical heating cycle. In particular, the nighttime sample can precede the daytime sample. No day–night temperature contrast is calculated by this availability pilot.

## Calendar coverage and provisional screening

Every imported location/year is checked against the inventory of source image IDs/dates and native grid cells. Duplicate images, duplicate downloads, missing native rows and truncated exports fail validation. If a whole export is absent, affected records remain `pending_export` with null counts. Only an explicit source inventory can establish zero source images.

Monthly and yearly denominators are all calendar UTC product dates in the requested period. Annual counts reconcile with monthly totals. Missing product dates are listed separately from present daily images with zero valid retrievals.

For each phase, a supported date has strict-QA, in-window data over at least the configured native-centre area fraction, initially 0.8. The provisional monthly screen requires at least 10 such dates and at least 0.5 of calendar dates in each phase. It additionally reports whether joint same-product-date support reaches the spatial criterion on at least 0.5 of dates. All settings remain editable diagnostic hypotheses in `config.json`.

`meets_exploratory_screen` reports a mechanical comparison with those hypotheses. It is not scientific qualification. Inspect QA/time histograms and seasonal failure patterns before proposing any new window or cutoff. Do not silently loosen criteria to produce matches. Clear-sky selection can bias inferred exposure, regardless of count.

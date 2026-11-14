# TerraTwin

Planetary analogue explorer for the NASA Space Apps Challenge 2026 team project. React, Vite, TypeScript, Tailwind CSS, React Leaflet, Recharts and Lucide. Entirely static, with no backend or API keys.

## Run locally

Use Node.js 22.12+ or Node 24 LTS.

```bash
cd TerraTwin
npm install
npm run dev
```

Open the local URL printed by Vite, usually http://localhost:5173.

```bash
npm test
npm run build
npm run preview
```

## Scientific datasets

The app loads the supplied preliminary terrain products directly from these files.

- `public/data/terratwin_mars_20_targets_harmonized.json` contains an array of 20 Mars targets from NASA MGS MOLA MEGDR.
- `public/data/terratwin_moon_15_targets_harmonized.json` contains an array of 15 Moon targets from NASA LRO LOLA LDEM_64 / polar DEM products.
- `public/data/earth_terrain_harmonized.geojson` contains 735 Earth candidate records from NASA SRTM. The existing validator accepts 731 and excludes four with p90 slope below mean slope. The excluded names are `Atacama_1_1`, `Tenerife_0_0`, `Tenerife_6_0`, and `Tenerife_6_2`. Source records remain intact.
- `public/data/terratwin_mars_gale.json` is retained as a legacy test file. The application uses Gale Crater from the 20-target harmonized Mars catalog.

Planetary records require `planet`, a unique `location`, numeric coordinates, `mean_slope_deg`, `p90_slope_deg`, `roughness_mean_m`, `elevation_stddev_m`, `mean_elevation_m`, positive integer `valid_pixels`, the 5,000 m `analysis_radius_m`, 463 m `grid_spacing_m`, and 463 m `pixel_spacing_x_m` / `pixel_spacing_y_m`. Source, processing and quality-status strings are required. Invalid targets appear as unavailable selector entries. Duplicate location identifiers invalidate that planet's catalog to avoid ambiguous selection.

Earth values remain in each Feature's `properties` and use the existing validation rules. Coordinates are required in properties even if a geometry exists. Slopes use degrees, roughness and elevation standard deviation use metres. Missing, null, nonfinite, string-valued and out-of-range terrain measurements are rejected. The existing p90-at-least-mean rule is preserved.

Planetary identifiers combine planet and exact location name. Longitudes above 180° are normalized by subtracting 360° in the adapter. Original coordinates and all source/processing metadata remain in each target's `metadata` and the exported result provenance. Terrain measurements are passed to scoring without rounding or rescaling. Rendering rounds display values only.

Requests are shared and cached for the page session. Switching planet or target uses already loaded records. Failed requests are evicted for retry. Planet-specific failures allow the other planet to remain usable. Aborted effects cannot commit old responses. Unknown or rejected selected identifiers produce an explicit unavailable state. There is no arbitrary-coordinate terrain analysis or interactive planetary map in this version. Thermal Testing and Dust & Solar retain their existing unavailable states.

All 35 planetary records report `pending_validation`. A 463 m output grid and 5 km analysis radius do not establish identical effective source resolution or accuracy. Bilinear resampling adds no new terrain detail. The files omit slope algorithms, 3×3 roughness implementation details (statistic, masks, edges and aggregation), elevation-standard-deviation conventions, and complete georeferencing definitions. Their numerical equivalence across products cannot be verified from these files. Confirm latitude/longitude conventions, DEM georeferencing, native source resolutions, vertical units/datums and sampling methods independently. The application presents preliminary terrain estimates with this qualification and applies no inferred corrections.

## Manual integration verification

Run `npm run dev`, open the printed URL, and keep Rover Mobility selected.

1. On Mars, verify that the selector lists 20 targets. Select Gale Crater, Jezero Crater, Olympus Mons, Planum Boreum and Planum Australe. Compare sidebar metrics with the corresponding raw records. Olympus Mons should display normalized longitude −133.8° while export metadata retains 226.2°.
2. Switch to Moon and verify 15 targets. Select Mare Tranquillitatis, Shackleton Crater and Peary Crater. Check target coordinates, four measurements, chart legend, table body label and exported planetary target.
3. Switch Mars → Moon → Mars and change multiple targets on each planet. Each planet retains its selected location. Confirm 731 candidates, four exclusions, updated scores/order/comparisons, and Earth marker selection from ranking cards.
4. Open Thermal Testing and Dust & Solar, verify their pending-data panels, and return to Rover Mobility. There are no purpose-weight presets or user-controlled weights in the existing app.
5. In a disposable checkout, simulate a missing or malformed planetary file and a missing metric, or use request interception. Check explicit errors/unavailable entries, absence of stale results, retry recovery, and availability of the unaffected planet. Original dataset files should stay intact.

Automated tests exercise all 35 target ranking pipelines, precision, normalization, exclusions, load failures, retry/caching and aborted responses. Browser rendering and interaction verification must be reported separately from these tests.

## Architecture and integration

- `src/types/index.ts` defines the shared `AnalysisResult`, feature comparisons, provenance and `ScientificModule<T>` adapter contract.
- `src/config/datasets.ts` centralizes base-path-aware dataset URLs and scientific limitations.
- `src/services/datasets.ts` loads and validates both planetary catalogs and the Earth GeoJSON, retaining original metadata and caching shared requests.
- `src/modules/roverMobility/scoring.ts` contains independent deterministic terrain scoring.
- `src/modules/thermalTesting/index.ts` and `src/modules/dustSolar/index.ts` define independent integration contracts and required-data descriptions. Calling their placeholder analysis throws an explicit unavailable error. The UI never calls them for fabricated results.
- `src/pages/App.tsx` manages target selection, module states, ranking, comparisons and JSON export.
- `src/components/EarthMap.tsx` provides selectable markers and selected-site focus.
- `tests/` covers scoring and missing-data handling.

To integrate another module, replace its dataset interface with explicit domain measurements, implement its `ScientificModule<T>` adapter, add loading and validation in services, and wire its validated results into the corresponding UI branch. Return the common result fields including module ID, target, Earth candidate ID and coordinates, score, comparisons, limitations and provenance. Keep module-specific scales and calculations in that module. The existing unavailable panels list the pending measurement requirements.

## Preliminary Rover Mobility methodology

For each feature, compute `min(abs(Earth − target) / fixedScale, 1)`. The score is `100 × (1 − mean(feature differences))`. All four features have equal weights. Scales are 30 degrees for mean slope, 45 degrees for p90 slope, 100 metres for roughness, and 1,000 metres for elevation standard deviation. These are documented MVP design choices requiring scientific calibration. No candidate-set min/max normalization is used. Adding candidates preserves existing scores. Ties sort by candidate identifier.

Charts express each raw measurement as a percentage of its fixed scale, while the table shows actual values and signed differences. Chart values may exceed 100% of a scale. Score contributions are capped. Export saves the selected result with provenance and limitations.

The percentage is a preliminary terrain similarity index. It has no validated probability, safety-rating or full planetary-environment interpretation. Gravity, atmosphere, unresolved obstacles, soil mechanics and dust require separate consideration. Rankings cover only the loaded candidate database.

## Deployment

```bash
npm ci
npm test
npm run build
```

Deploy the generated `dist/` directory to any static host. On Netlify or Cloudflare Pages use build command `npm run build` and output directory `dist`. On Vercel select Vite with the same output directory. The app uses page anchors and needs no server-side route rewrites. For a subdirectory deployment, set Vite's `base` option to the deployment prefix, rebuild, and keep the data folder inside the generated output. All data fetches honor `BASE_URL`.

React Leaflet loads OpenStreetMap standard tiles with contributor attribution. Internet connectivity is needed for basemap tiles and Google Fonts. Rankings and charts are computed locally from the bundled datasets. Tile failure can leave the basemap blank while the candidate list and comparisons remain usable. The supplied terrain records identify their source products, and source links provide NASA PDS/MOLA and NASA Earthdata references.

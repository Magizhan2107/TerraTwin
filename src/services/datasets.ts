import { DATA_PATHS } from '../config/datasets';
import { FEATURES } from '../modules/roverMobility/scoring';
import type { Dataset, Terrain, Provenance, PlanetaryBody, PlanetaryTarget, TargetCatalog, EarthDataset, PlanetaryDatasets } from '../types';
function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
export function parseTerrain(value: unknown, fallbackId: string): Terrain | null {
 if (!record(value)) return null;
 const fields = [...FEATURES.map(f => f.key), 'latitude', 'longitude'];
 if (fields.some(key => typeof value[key] !== 'number' || !Number.isFinite(value[key]))) return null;
 if (Math.abs(value.latitude as number) > 90 || Math.abs(value.longitude as number) > 180) return null;
 if (FEATURES.some(f => (value[f.key] as number) < 0) || (value.mean_slope_deg as number) > 90 || (value.p90_slope_deg as number) > 90 || (value.p90_slope_deg as number) < (value.mean_slope_deg as number)) return null;
 return { ...value, id: String(value.id ?? fallbackId), name: String(value.name ?? value.location_name ?? fallbackId) } as unknown as Terrain;
}
export function validateEarthDataset(earth: unknown): EarthDataset {
 if (!record(earth) || earth.type !== 'FeatureCollection' || !Array.isArray(earth.features)) throw new Error('Earth dataset must be a GeoJSON FeatureCollection.');
 const seen = new Set<string>();
 const candidates: Terrain[] = [];
 let excluded = 0;
 earth.features.forEach((feature, i) => {
  const candidate = record(feature) && feature.type === 'Feature' ? parseTerrain(feature.properties, String(feature.id ?? `candidate-${i + 1}`)) : null;
  if (!candidate || seen.has(candidate.id)) { excluded++; return; }
  seen.add(candidate.id); candidates.push(candidate);
 });
 const sources = [...new Set(candidates.map(candidate => (candidate as unknown as Record<string, unknown>).source).filter((source): source is string => typeof source === 'string'))];
 const meta = record(earth.provenance) ? earth.provenance : {};
 const source = typeof meta.source === 'string' ? meta.source : sources.join(', ') || 'Earth dataset — provenance unspecified';
 return { candidates, excluded, provenance: [{ source, demonstration: meta.demonstration === true || !sources.length && meta.demonstration !== false, metadata: meta }] };
}
// Retain the legacy validator for existing callers, without using the Gale file in the app.
export function validateDatasets(mars: unknown, earth: unknown): Dataset {
 const target = parseTerrain(mars, 'gale');
 if (!target) throw new Error('Mars dataset has missing or invalid required measurements.');
 const validated = validateEarthDataset(earth);
 const meta = record(mars) && record(mars.provenance) ? mars.provenance : {};
 return { ...validated, target, provenance: [{ source: typeof meta.source === 'string' ? meta.source : 'Mars dataset — provenance unspecified', demonstration: meta.demonstration !== false }, ...validated.provenance] };
}
export function validatePlanetaryDataset(data: unknown, body: PlanetaryBody): TargetCatalog {
 if (!Array.isArray(data)) throw new Error(`${body} dataset must be an array of precomputed targets.`);
 const targets: PlanetaryTarget[] = [];
 const rejected: TargetCatalog['rejected'] = [];
 const identifiers = new Set<string>();
 data.forEach((raw, i) => {
  const name = record(raw) && typeof raw.location === 'string' && raw.location.trim() ? raw.location : `Invalid record ${i + 1}`;
  const id = `${body}:${name}`;
  if (identifiers.has(id)) throw new Error(`${body} dataset has a duplicate location identifier: ${name}`);
  identifiers.add(id);
  try {
   if (!record(raw) || typeof raw.location !== 'string' || !raw.location.trim() || raw.planet !== body) throw new Error('Missing location or mismatched planet.');
   if (typeof raw.longitude !== 'number' || !Number.isFinite(raw.longitude) || raw.longitude < -180 || raw.longitude > 360) throw new Error('Longitude must be in −180…180 or 0…360 degrees.');
   // Normalize coordinates only. Terrain measurements retain their original numbers.
   const longitude = raw.longitude > 180 ? raw.longitude - 360 : raw.longitude;
   const terrain = parseTerrain({ ...raw, id, name, longitude }, id);
   if (!terrain) throw new Error('Missing, nonfinite or out-of-range terrain measurements or coordinates.');
   if (raw.analysis_radius_m !== 5000 || raw.grid_spacing_m !== 463 || raw.pixel_spacing_x_m !== 463 || raw.pixel_spacing_y_m !== 463) throw new Error('Expected a 463 m output grid and 5 km analysis radius.');
   if (typeof raw.mean_elevation_m !== 'number' || !Number.isFinite(raw.mean_elevation_m) || typeof raw.valid_pixels !== 'number' || !Number.isInteger(raw.valid_pixels) || raw.valid_pixels <= 0) throw new Error('Invalid elevation or valid-pixel count.');
   if (typeof raw.source !== 'string' || !raw.source.trim() || typeof raw.processing !== 'string' || !raw.processing.trim() || typeof raw.data_quality_status !== 'string' || !raw.data_quality_status.trim()) throw new Error('Missing source, processing or quality metadata.');
   targets.push({ ...terrain, planet: body, metadata: { ...raw } });
  } catch (error) {
   rejected.push({ id, name, error: error instanceof Error ? error.message : String(error) });
  }
 });
 return { targets, rejected };
}
export function targetProvenance(target: PlanetaryTarget): Provenance {
 return { source: `${target.metadata.source} · ${target.name} · ${target.metadata.processing} · ${target.metadata.data_quality_status}`, demonstration: false, metadata: target.metadata };
}
// Share in-flight and successful requests across selections and React StrictMode effects.
// Failed requests are evicted so the existing Retry action can fetch them again.
const requests = new Map<string, Promise<unknown>>();
function loadJson(path: string): Promise<unknown> {
 const cached = requests.get(path);
 if (cached) return cached;
 const request = (async () => {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Dataset request failed (${response.status}) at ${path}`);
  try { return await response.json(); }
  catch { throw new Error(`Invalid JSON at ${path}`); }
 })().catch(error => { requests.delete(path); throw error; });
 requests.set(path, request);
 return request;
}
export async function loadDatasets(signal?: AbortSignal): Promise<PlanetaryDatasets> {
 signal?.throwIfAborted();
 const loadPlanet = async (body: PlanetaryBody, path: string): Promise<TargetCatalog> => {
  try {
   const catalog = validatePlanetaryDataset(await loadJson(path), body);
   if (catalog.rejected.length || !catalog.targets.length) requests.delete(path);
   return catalog;
  }
  catch (error) { requests.delete(path); return { targets: [], rejected: [], error: error instanceof Error ? error.message : String(error) }; }
 };
 const [earth, mars, moon] = await Promise.all([
  loadJson(DATA_PATHS.earth).then(validateEarthDataset).catch(error => { requests.delete(DATA_PATHS.earth); throw error; }),
  loadPlanet('Mars', DATA_PATHS.mars),
  loadPlanet('Moon', DATA_PATHS.moon),
 ]);
 signal?.throwIfAborted();
 return { earth, planets: { Mars: mars, Moon: moon } };
}

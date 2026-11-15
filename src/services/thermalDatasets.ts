import { THERMAL_DATA_PATHS } from '../config/datasets';
import type { PlanetaryTarget, Terrain } from '../types';
import type { EarthThermalEvidence, EarthThermalPeriod, EarthThermalValidation, MarsThermalObservation, MarsThermalTarget } from '../types/thermal';

const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const count = (v: unknown): v is number => finite(v) && Number.isInteger(v) && v >= 0;
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);

// Successful/in-flight requests are shared. A failed request is evicted for Retry.
const requests = new Map<string, Promise<unknown>>();
export function invalidateThermalAsset(path: string) { requests.delete(path); }
export async function loadJson(path: string): Promise<unknown> {
 const cached = requests.get(path);
 if (cached) return cached;
 const request = (async () => {
  let response: Response;
  try { response = await fetch(path); }
  catch { throw new Error(`Thermal asset could not be loaded. Check your connection and retry: ${path}`); }
  if (!response.ok) throw new Error(`Thermal asset could not be loaded (${response.status}): ${path}`);
  try { return await response.json(); }
  catch { throw new Error(`Thermal asset contains invalid JSON: ${path}`); }
 })().catch(error => { requests.delete(path); throw error; });
 requests.set(path, request);
 return request;
}

export const EARTH_METRICS = [
 ['lst_valid', 'Valid LST pixel-dates'], ['qc_present', 'Valid LST with usable QC'],
 ['qc_missing', 'Valid LST with unknown QC'], ['strict_qa', 'Strict QA pixel-dates'],
 ['relaxed_qa', 'Relaxed QA pixel-dates'], ['time_valid', 'Valid observation-time pixel-dates'],
 ['phase_window', 'In-window pixel-dates before QA'],
 ['strict_qa_in_phase', 'Strict QA + window pixel-dates'],
 ['relaxed_qa_in_phase', 'Relaxed QA + window pixel-dates'],
] as const;

export function validateEarthThermal(data: unknown, proof: unknown, site: Terrain): EarthThermalEvidence {
 if (!record(data) || data.schema_version !== 'earth-thermal-cloud/1.0.0' || !Array.isArray(data.records) || data.records.length !== 13) throw new Error('Earth thermal evidence must contain 13 versioned diagnostic periods.');
 if (site.id !== '24') throw new Error('The validated thermal demonstration is restricted to canonical Earth ID 24.');
 const expected = new Set(['2021', ...Array.from({ length: 12 }, (_, i) => `2021-${String(i + 1).padStart(2, '0')}`)]);
 for (const r of data.records) {
  if (!record(r) || typeof r.period !== 'string' || !expected.delete(r.period)) throw new Error('Duplicate or unexpected Earth thermal period.');
  if (r.schema_version !== data.schema_version || r.location_id !== site.id || r.name !== site.name || r.planet !== 'Earth' || r.canonical_latitude !== site.latitude || r.canonical_longitude !== site.longitude) throw new Error('Earth thermal evidence does not match the canonical site.');
  if (r.run_id !== 'thermal_cloud_validation_001' || r.dataset_id !== 'MODIS/061/MYD11A1' || r.mission_suitability !== 'not_assessed' || r.footprint_radius_m !== 5000 || !hash(r.config_sha256) || !hash(r.catalog_sha256)) throw new Error('Earth thermal provenance is missing or incompatible.');
  if (r.period_type !== (r.period === '2021' ? 'year' : 'month')) throw new Error('Earth thermal period type is inconsistent.');
  for (const key of ['calendar_dates', 'source_product_dates', 'native_centres', 'pixel_date_records']) if (!count(r[key])) throw new Error(`Invalid Earth diagnostic: ${key}`);
  if ((r.calendar_dates as number) <= 0 || (r.native_centres as number) <= 0 || (r.source_product_dates as number) > (r.calendar_dates as number) || r.pixel_date_records !== (r.source_product_dates as number) * (r.native_centres as number)) throw new Error('Earth observation/date accounting is inconsistent.');
  for (const phase of ['day', 'night']) {
   for (const [metric] of EARTH_METRICS) {
    if (!count(r[`${phase}__${metric}__pixels`]) || !count(r[`${phase}__${metric}__dates`]) || !count(r[`${phase}__${metric}__centres`])) throw new Error(`Missing Earth diagnostic: ${phase} ${metric}`);
   }
   if (!count(r[`${phase}__supported_dates`]) || !finite(r[`${phase}__supported_calendar_fraction`])) throw new Error('Missing spatial/calendar coverage diagnostics.');
  }
 }
 if (expected.size) throw new Error('Earth thermal periods are missing.');
 if (!record(proof) || proof.conclusion !== 'PASS' || proof.periods !== 13 || !count(proof.matching_fields) || !count(proof.numeric_comparisons) || !Array.isArray(proof.numerical_differences) || proof.numerical_differences.length || ['missing_fields','missing_records','unexpected_fields','mismatched_fields','unverified_fields'].some(k => proof[k] !== 0)) throw new Error('Earth cloud/local validation evidence is missing or has not passed.');
 return { records: data.records as EarthThermalPeriod[], validation: proof as unknown as EarthThermalValidation };
}

function observation(value: unknown): MarsThermalObservation | null {
 if (value === null || value === undefined) return null;
 if (!record(value) || value.temperature_unit !== 'K' || value.same_day_diurnal_pair !== false) throw new Error('Mars thermal units or unpaired-observation status is invalid.');
 for (const key of ['mean_k','min_k','max_k','local_time','coverage','solar_longitude']) if (value[key] != null && !finite(value[key])) throw new Error(`Invalid Mars thermal measurement: ${key}`);
 if (finite(value.coverage) && (value.coverage < 0 || value.coverage > 1)) throw new Error('Invalid Mars spatial coverage fraction.');
 for (const key of ['observation_id','start_time','measurement_type','url','processing_note','projection_validation']) if (typeof value[key] !== 'string' || !value[key]) throw new Error(`Missing Mars provenance: ${key}`);
 if (!Number.isFinite(Date.parse(value.start_time as string)) || !(value.url as string).startsWith('https://')) throw new Error('Invalid Mars acquisition date or source URL.');
 return value as unknown as MarsThermalObservation;
}

export function validateMarsThermal(data: unknown, targets: PlanetaryTarget[]): MarsThermalTarget[] {
 if (!Array.isArray(data) || data.length !== targets.length || targets.length !== 20) throw new Error('Mars thermal evidence must match all 20 canonical targets.');
 const byName = new Map(targets.map(t => [t.name, t]));
 const seen = new Set<string>();
 return data.map(raw => {
  if (!record(raw) || raw.planet !== 'Mars' || typeof raw.location !== 'string') throw new Error('Invalid Mars thermal target identity.');
  const target = byName.get(raw.location);
  if (!target || seen.has(target.id)) throw new Error('Unknown or duplicate Mars thermal target.');
  seen.add(target.id);
  // The integrated file retains terrain, but only the existing terrain file drives Rover Mobility.
  if (Object.entries(target.metadata).some(([key, value]) => JSON.stringify(raw[key]) !== JSON.stringify(value))) throw new Error(`Mars source identity/terrain differs from canonical target: ${target.name}`);
  if (!record(raw.thermal) || raw.thermal.same_day_diurnal_pair !== false) throw new Error('Mars thermal pairing metadata is missing.');
  return { target, morning: observation(raw.thermal.morning), evening: observation(raw.thermal.evening) };
 });
}

export async function loadEarthThermal(site: Terrain): Promise<EarthThermalEvidence> {
 try {
  const [data, proof] = await Promise.all([loadJson(THERMAL_DATA_PATHS.earth), loadJson(THERMAL_DATA_PATHS.earthValidation)]);
  return validateEarthThermal(data, proof, site);
 }
 catch (error) { requests.delete(THERMAL_DATA_PATHS.earth); requests.delete(THERMAL_DATA_PATHS.earthValidation); throw error; }
}
export async function loadMarsThermal(targets: PlanetaryTarget[]): Promise<MarsThermalTarget[]> {
 try { return validateMarsThermal(await loadJson(THERMAL_DATA_PATHS.mars), targets); }
 catch (error) { requests.delete(THERMAL_DATA_PATHS.mars); throw error; }
}

export function selectMarsThermal(targets: MarsThermalTarget[], id: string): MarsThermalTarget | undefined {
 return targets.find(row => row.target.id === id); // Never substitute a different target.
}

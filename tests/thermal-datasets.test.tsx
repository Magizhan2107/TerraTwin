import publishedEarthText from '../public/data/thermal/earth_atacama_2021_availability.json?raw';
import publishedProofText from '../public/data/thermal/earth_atacama_2021_validation.json?raw';
import originalEarthText from '../experiments/earth_thermal_pilot/outputs/cloud/thermal_cloud_validation_001_24_2021_cli_geometry_fix.json?raw';
import originalProofText from '../experiments/earth_thermal_pilot/outputs/cloud/thermal_cloud_validation_001_geometry_fix_validation.json?raw';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import marsSource from '../public/data/terratwin_mars_20_mola_themis_integrated.json';
import marsCanonical from '../public/data/terratwin_mars_20_targets_harmonized.json';
import moonCanonical from '../public/data/terratwin_moon_15_targets_harmonized.json';
import earthSource from '../public/data/thermal/earth_atacama_2021_availability.json';
import proof from '../public/data/thermal/earth_atacama_2021_validation.json';
import earthText from '../public/data/earth_terrain_harmonized.geojson?raw';
import { validateEarthDataset, validatePlanetaryDataset } from '../src/services/datasets';
import { validateEarthThermal, validateMarsThermal, selectMarsThermal } from '../src/services/thermalDatasets';
import ThermalObservations, { MarsObservationCard, thermalNumber } from '../src/components/ThermalObservations';
import { analyze, observations } from '../src/modules/thermalTesting';
import { LUNAR_SITES } from '../src/services/lunarThermal';
import { MOON_UNAVAILABLE } from '../src/components/LunarThermalObservations';
import { THERMAL_DATA_PATHS } from '../src/config/datasets';

const mars = validatePlanetaryDataset(marsCanonical, 'Mars').targets;
const moon = validatePlanetaryDataset(moonCanonical, 'Moon').targets;
const site = validateEarthDataset(JSON.parse(earthText)).candidates.find(s => s.id === '24')!;

describe('thermal observations use existing scientific artifacts', () => {
 it('publishes Earth artifacts as byte-identical copies', () => {
  expect(publishedEarthText).toBe(originalEarthText);
  expect(publishedProofText).toBe(originalProofText);
 });
 it('loads 12 monthly records and a yearly record without changing any property', () => {
  const data = validateEarthThermal(earthSource, proof, site);
  expect(data.records).toEqual(earthSource.records);
  expect(data.records.filter(r => r.period_type === 'month')).toHaveLength(12);
  const year = data.records.find(r => r.period === '2021')!;
  expect([year.source_product_dates, year.native_centres, year.pixel_date_records]).toEqual([365,90,32850]);
  expect(year.night__strict_qa_in_phase__dates).toBe(0);
  expect(year.night__qc_missing__pixels).toBe(20112);
  expect(data.validation.matching_fields).toBe(2665);
  expect(data.validation.numeric_comparisons).toBe(2535);
  expect(Object.keys(year).some(key => key.includes('mean_k') || key.includes('contrast'))).toBe(false);
 });
 it('rejects missing, duplicated, corrupted or mismatched Earth evidence', () => {
  for (const change of [
   (d: any) => d.records.pop(),
   (d: any) => d.records[0].location_id = '73',
   (d: any) => d.records[0].canonical_latitude = 0,
   (d: any) => d.records[0].night__lst_valid__pixels = null,
   (d: any) => d.records[1].period = d.records[0].period,
   (d: any) => d.records[0].pixel_date_records = 0,
  ]) {
   const d = structuredClone(earthSource); change(d);
   expect(() => validateEarthThermal(d, proof, site)).toThrow();
  }
  expect(() => validateEarthThermal(earthSource, { ...proof, conclusion: 'FAIL' }, site)).toThrow('validation');
 });
 it('matches all 20 Mars canonical targets without changing measurements or terrain fields', () => {
  const before = structuredClone(marsSource);
  const data = validateMarsThermal(marsSource, mars);
  expect(data).toHaveLength(20);
  for (const row of data) {
   const raw = marsSource.find(r => r.location === row.target.name)!;
   expect(row.target.id).toBe(`Mars:${raw.location}`);
   expect(row.morning).toEqual(raw.thermal.morning);
   expect(row.evening).toEqual(raw.thermal.evening);
   expect(row.target.metadata).toEqual(marsCanonical.find(r => r.location === row.target.name));
   expect(selectMarsThermal(data, row.target.id)).toBe(row);
  }
  expect(selectMarsThermal(data, 'Mars:missing')).toBeUndefined();
  expect(marsSource).toEqual(before);
 });
 it('switches Gale/Jezero/Olympus without substituting or retaining prior measurements', () => {
  const data = validateMarsThermal(marsSource, mars);
  const gale = selectMarsThermal(data, 'Mars:Gale Crater')!;
  const jezero = selectMarsThermal(data, 'Mars:Jezero Crater')!;
  const olympus = selectMarsThermal(data, 'Mars:Olympus Mons')!;
  expect(jezero.morning?.mean_k).not.toBe(gale.morning?.mean_k);
  expect(olympus.evening?.min_k).toBeNull();
  expect(selectMarsThermal(data, gale.target.id)).toBe(gale);
 });
 it('displays null/absent Mars ranges as unavailable, never zero', () => {
  const data = validateMarsThermal(marsSource, mars);
  const card = selectMarsThermal(data, 'Mars:Gusev Crater')!.evening;
  const html = renderToStaticMarkup(<MarsObservationCard phase="Evening" observation={card}/>);
  expect(html.match(/Unavailable/g)).toHaveLength(2);
  expect(html).toContain('213.5 K');
  expect(html).toContain(card!.observation_id);
  expect(html).not.toContain('0 K');
  expect(thermalNumber(undefined)).toBe('Unavailable');
  expect(thermalNumber(null)).toBe('Unavailable');
  expect(thermalNumber(NaN)).toBe('Unavailable');
  expect(thermalNumber(0)).toBe('0');
  const missing = structuredClone(marsSource) as any[];
  delete missing[0].thermal.morning.min_k;
  expect(validateMarsThermal(missing, mars)[0].morning?.min_k).toBeUndefined();
 });
 it('rejects identity, unit and numeric corruption without changing scientific thresholds', () => {
  for (const change of [
   (d: any) => d[0].location = 'Unknown',
   (d: any) => d[0].latitude = 0,
   (d: any) => d[0].roughness_mean_m = 0,
   (d: any) => d[0].thermal.morning.temperature_unit = 'C',
   (d: any) => d[0].thermal.same_day_diurnal_pair = true,
   (d: any) => d[0].thermal.evening.mean_k = '200',
  ]) {
   const d = structuredClone(marsSource); change(d);
   expect(() => validateMarsThermal(d, mars)).toThrow();
  }
 });
 it('keeps absent observations unavailable and never invokes thermal ranking', () => {
  const d = structuredClone(marsSource) as any[];
  d[0].thermal.morning = null;
  expect(validateMarsThermal(d, mars)[0].morning).toBeNull();
  expect(renderToStaticMarkup(<MarsObservationCard phase="Morning" observation={null}/>)).toContain('Observation unavailable');
  expect(observations.ranking).toBe('unavailable');
  expect(() => analyze()).toThrow('not integrated');
 });
 it('shows canonical Moon identities with polar loading or nonpolar unavailability', () => {
  expect(moon).toHaveLength(15);
  for (const target of moon) {
   const html = renderToStaticMarkup(<ThermalObservations body="Moon" target={target} marsTargets={mars} earthSite={site}/>);
   expect(html).toContain(Object.hasOwn(LUNAR_SITES, target.id) ? 'Loading lunar Diviner profiles' : MOON_UNAVAILABLE);
   expect(html).toContain(target.name);
   expect(html).toContain('Thermal analogue ranking and thermal scores are unavailable');
   expect(html).not.toContain('Spatial mean brightness temperature');
  }
 });
});

describe('thermal asset loading and recoverable failures', () => {
 beforeEach(() => vi.resetModules());
 afterEach(() => vi.unstubAllGlobals());
 const response = (path: string) => path === THERMAL_DATA_PATHS.earth ? earthSource : path === THERMAL_DATA_PATHS.earthValidation ? proof : marsSource;
 const goodFetch = () => vi.fn(async (path: string) => ({ ok: true, json: async () => response(path) }));
 it('shares requests across target switches and never uses a backend', async () => {
  const fetch = goodFetch(); vi.stubGlobal('fetch', fetch);
  const { loadEarthThermal, loadMarsThermal } = await import('../src/services/thermalDatasets');
  const [earth, marsData] = await Promise.all([loadEarthThermal(site), loadMarsThermal(mars)]);
  expect(earth.records).toHaveLength(13); expect(marsData).toHaveLength(20);
  await Promise.all([loadEarthThermal(site), loadMarsThermal(mars)]);
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls.every(([path]) => Object.values(THERMAL_DATA_PATHS).includes(path))).toBe(true);
 });
 it('isolates a failed Earth asset from available Mars data and supports retry', async () => {
  const good = goodFetch();
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path === THERMAL_DATA_PATHS.earth ? { ok: false, status: 404 } : good(path)));
  const { loadEarthThermal, loadMarsThermal } = await import('../src/services/thermalDatasets');
  await expect(loadEarthThermal(site)).rejects.toThrow('404');
  expect(await loadMarsThermal(mars)).toHaveLength(20);
  vi.stubGlobal('fetch', goodFetch());
  expect((await loadEarthThermal(site)).records).toHaveLength(13);
 });
 it('reports invalid JSON and retries without a stale default target', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => { throw new Error('broken JSON'); } })));
  const { loadMarsThermal } = await import('../src/services/thermalDatasets');
  await expect(loadMarsThermal(mars)).rejects.toThrow('invalid JSON');
  vi.stubGlobal('fetch', goodFetch());
  expect(await loadMarsThermal(mars)).toHaveLength(20);
 });
 it('evicts scientifically incompatible assets so retry can recover', async () => {
  const corrupted = structuredClone(marsSource);
  corrupted[0].thermal.same_day_diurnal_pair = true as false;
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => corrupted })));
  const { loadMarsThermal } = await import('../src/services/thermalDatasets');
  await expect(loadMarsThermal(mars)).rejects.toThrow('pairing metadata');
  vi.stubGlobal('fetch', goodFetch());
  expect(await loadMarsThermal(mars)).toHaveLength(20);
 });
 it('reports network failures without fabricated diagnostics', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network unavailable')));
  const { loadEarthThermal } = await import('../src/services/thermalDatasets');
  await expect(loadEarthThermal(site)).rejects.toThrow('Check your connection and retry');
 });
});

import earthText from '../public/data/earth_terrain_harmonized.geojson?raw';
import marsText from '../public/data/terratwin_mars_20_targets_harmonized.json?raw';
import moonText from '../public/data/terratwin_moon_15_targets_harmonized.json?raw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { validateEarthDataset, validatePlanetaryDataset, targetProvenance } from '../src/services/datasets';
import { FEATURES, rankCandidates } from '../src/modules/roverMobility/scoring';
import type { PlanetaryBody } from '../src/types';

const earthRaw = JSON.parse(earthText);
const marsRaw = JSON.parse(marsText);
const moonRaw = JSON.parse(moonText);
const earth = validateEarthDataset(earthRaw);
const mars = validatePlanetaryDataset(marsRaw, 'Mars');
const moon = validatePlanetaryDataset(moonRaw, 'Moon');

describe('actual harmonized datasets', () => {
 it('preserves the existing Earth validation and every accepted measurement', () => {
  expect(earthRaw.features).toHaveLength(735);
  expect(earth.candidates).toHaveLength(731);
  expect(earth.excluded).toBe(4);
  const accepted = new Set(earth.candidates.map(candidate => candidate.id));
  expect(earthRaw.features.filter((feature: { id: string }) => !accepted.has(feature.id)).map((feature: { properties: { name: string } }) => feature.properties.name)).toEqual(['Atacama_1_1', 'Tenerife_0_0', 'Tenerife_6_0', 'Tenerife_6_2']);
  for (const candidate of earth.candidates) {
   const raw = earthRaw.features.find((feature: { id: string }) => feature.id === candidate.id).properties;
   expect(candidate.latitude).toBe(raw.latitude);
   expect(candidate.longitude).toBe(raw.longitude);
   for (const feature of FEATURES) expect(candidate[feature.key]).toBe(raw[feature.key]);
  }
 });
 it('accepts all 35 unique targets with full precision and original metadata', () => {
  expect(mars.targets).toHaveLength(20); expect(moon.targets).toHaveLength(15);
  expect(mars.rejected).toEqual([]); expect(moon.rejected).toEqual([]);
  const targets = [...mars.targets, ...moon.targets];
  expect(new Set(targets.map(target => target.id)).size).toBe(35);
  for (const target of targets) {
   const raw = (target.planet === 'Mars' ? marsRaw : moonRaw).find((record: { location: string }) => record.location === target.name);
   for (const feature of FEATURES) expect(target[feature.key]).toBe(raw[feature.key]);
   expect(target.metadata).toEqual(raw);
   expect(target.longitude).toBe(raw.longitude > 180 ? raw.longitude - 360 : raw.longitude);
   expect(targetProvenance(target).metadata).toEqual(raw);
  }
 });
 it.each([...mars.targets, ...moon.targets].map(target => [target.name, target] as const))('ranks the full Earth database for %s with correct target labels and comparisons', (_name, target) => {
  const results = rankCandidates(target, earth.candidates, [targetProvenance(target), ...earth.provenance]);
  expect(results).toHaveLength(731);
  expect(results.every(result => result.planetaryTarget.body === target.planet && result.planetaryTarget.id === target.id && Number.isFinite(result.similarityScore))).toBe(true);
  results.forEach((result, i) => {
   if (i) expect(result.similarityScore).toBeLessThanOrEqual(results[i - 1].similarityScore);
   result.featureComparisons.forEach((comparison, featureIndex) => expect(comparison.target).toBe(target[FEATURES[featureIndex].key]));
  });
 });
 it('uses the harmonized Gale values, and recomputes different rankings across planet and target switches', () => {
  const names = ['Gale Crater', 'Jezero Crater', 'Olympus Mons', 'Planum Boreum', 'Planum Australe', 'Shackleton Crater', 'Peary Crater', 'Mare Tranquillitatis', 'Gale Crater'];
  const targets = [...mars.targets, ...moon.targets];
  const rankings = names.map(name => {
   const target = targets.find(candidate => candidate.name === name)!;
   const result = rankCandidates(target, earth.candidates);
   expect(result[0].featureComparisons[0].target).toBe(target.mean_slope_deg);
   return result.map(candidate => [candidate.earthCandidateId, candidate.similarityScore]);
  });
  expect(rankings[0]).toEqual(rankings[8]);
  for (let i = 1; i < 8; i++) expect(rankings[i]).not.toEqual(rankings[i - 1]);
  expect(mars.targets.find(target => target.name === 'Gale Crater')?.mean_slope_deg).toBe(marsRaw[0].mean_slope_deg);
  expect(mars.targets.find(target => target.id === 'Mars:unknown')).toBeUndefined();
 });
});

describe('planetary runtime validation', () => {
 it.each([null, undefined, NaN, Infinity, '1.5'])('rejects missing or invalid metrics (%s) without substituting another target', value => {
  const catalog = validatePlanetaryDataset([{ ...marsRaw[0], roughness_mean_m: value }, marsRaw[1]], 'Mars');
  expect(catalog.targets.map(target => target.name)).toEqual(['Jezero Crater']);
  expect(catalog.rejected[0].name).toBe('Gale Crater');
 });
 it.each([
  { planet: 'Moon' }, { latitude: 91 }, { longitude: 361 }, { longitude: -181 },
  { analysis_radius_m: 1000 }, { pixel_spacing_x_m: 100 }, { source: '' }, { valid_pixels: 0 },
 ])('reports incompatible fields %j', patch => expect(validatePlanetaryDataset([{ ...marsRaw[0], ...patch }], 'Mars').rejected).toHaveLength(1));
 it('rejects ambiguous identifiers and incorrect root structures', () => {
  expect(() => validatePlanetaryDataset([marsRaw[0], marsRaw[0]], 'Mars')).toThrow('duplicate');
  expect(() => validatePlanetaryDataset({ targets: marsRaw }, 'Mars')).toThrow('array');
  expect(validatePlanetaryDataset([], 'Moon').targets).toEqual([]);
 });
});

describe('cached loading and failures', () => {
 beforeEach(() => vi.resetModules());
 afterEach(() => vi.unstubAllGlobals());
 const mockFetch = (failBody?: PlanetaryBody, invalidJson = false) => vi.fn(async (path: string) => {
  const planet = path.includes('mars_20') ? 'Mars' : path.includes('moon_15') ? 'Moon' : undefined;
  if (planet === failBody && failBody) return { ok: !invalidJson ? false : true, status: 404, json: async () => { throw new SyntaxError('Unexpected token'); } };
  return { ok: true, json: async () => planet === 'Mars' ? marsRaw : planet === 'Moon' ? moonRaw : earthRaw };
 });
 it('shares concurrent and subsequent requests without using the legacy Gale file', async () => {
  const fetch = mockFetch(); vi.stubGlobal('fetch', fetch);
  const { loadDatasets } = await import('../src/services/datasets');
  const [first, second] = await Promise.all([loadDatasets(), loadDatasets()]);
  expect(first.planets.Mars.targets).toHaveLength(20); expect(second.planets.Moon.targets).toHaveLength(15);
  await loadDatasets(); expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls.every(([path]) => !path.includes('mars_gale'))).toBe(true);
 });
 it.each([false, true])('isolates a missing/invalid Moon file and allows retry (%s)', async invalidJson => {
  const fetch = mockFetch('Moon', invalidJson); vi.stubGlobal('fetch', fetch);
  const { loadDatasets } = await import('../src/services/datasets');
  const first = await loadDatasets();
  expect(first.planets.Moon.targets).toEqual([]);
  expect(first.planets.Moon.error).toContain(invalidJson ? 'Invalid JSON' : '404');
  expect(first.planets.Mars.targets).toHaveLength(20);
  vi.stubGlobal('fetch', mockFetch());
  const retried = await loadDatasets(); expect(retried.planets.Moon.targets).toHaveLength(15);
 });
 it('can retry a catalog whose target records were invalid', async () => {
  const fetch = mockFetch();
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path.includes('moon_15') ? { ok: true, json: async () => [{ ...moonRaw[0], mean_slope_deg: null }] } : fetch(path)));
  const { loadDatasets } = await import('../src/services/datasets');
  const invalid = await loadDatasets();
  expect(invalid.planets.Moon.targets).toHaveLength(0);
  expect(invalid.planets.Moon.rejected).toHaveLength(1);
  const retryFetch = mockFetch(); vi.stubGlobal('fetch', retryFetch);
  expect((await loadDatasets()).planets.Moon.targets).toHaveLength(15);
  expect(retryFetch).toHaveBeenCalledTimes(1);
 });
 it('rejects Earth network failures explicitly', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network unavailable')));
  const { loadDatasets } = await import('../src/services/datasets');
  await expect(loadDatasets()).rejects.toThrow('Network unavailable');
 });
 it('prevents an aborted earlier load from committing after a newer load', async () => {
  let release!: () => void;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  const fetch = mockFetch();
  vi.stubGlobal('fetch', vi.fn(async (path: string) => { await delayed; return fetch(path); }));
  const { loadDatasets } = await import('../src/services/datasets');
  const oldController = new AbortController();
  const old = loadDatasets(oldController.signal);
  const assertion = expect(old).rejects.toMatchObject({ name: 'AbortError' });
  oldController.abort();
  const current = loadDatasets();
  release(); await assertion;
  expect((await current).planets.Moon.targets).toHaveLength(15);
  expect(fetch).toHaveBeenCalledTimes(3);
 });
});

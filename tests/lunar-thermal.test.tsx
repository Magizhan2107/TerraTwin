import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import profiles from '../public/data/thermal/lunar_polar/terratwin_moon_4_polar_profiles.json';
import profileText from '../public/data/thermal/lunar_polar/terratwin_moon_4_polar_profiles.json?raw';
import csvText from '../public/data/thermal/lunar_polar/terratwin_moon_4_polar_profiles.csv?raw';
import coverageText from '../public/data/thermal/lunar_polar/polar_coverage_summary.csv?raw';
import manifest from '../public/data/thermal/lunar_polar/manifest.json';
import canonical from '../public/data/terratwin_moon_15_targets_harmonized.json';
import { validatePlanetaryDataset } from '../src/services/datasets';
import { LUNAR_SITES, selectLunarThermal, validateLunarThermal } from '../src/services/lunarThermal';
import LunarThermalObservations, { LUNAR_VALIDATION, LunarProfileTable, MOON_UNAVAILABLE } from '../src/components/LunarThermalObservations';
import { THERMAL_DATA_PATHS } from '../src/config/datasets';
import { analyze } from '../src/modules/thermalTesting';

const targets = validatePlanetaryDataset(canonical, 'Moon').targets;
const data = validateLunarThermal(profiles);
describe('lunar saved-output integrity and canonical matching', () => {
 it('matches every published payload byte count and SHA256 against the manifest', async () => {
  const payloads = {
   'terratwin_moon_4_polar_profiles.json': profileText,
   'terratwin_moon_4_polar_profiles.csv': csvText,
   'polar_coverage_summary.csv': coverageText,
  };
  for (const [name, text] of Object.entries(payloads)) {
   const bytes = new TextEncoder().encode(text);
   const digest = await crypto.subtle.digest('SHA-256', bytes);
   const hex = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
   expect({ bytes: bytes.length, sha256: hex }).toEqual(manifest.files[name as keyof typeof manifest.files]);
  }
 });
 it('preserves 768 records, 719 valid bins, 49 null bins and 384 products without mutation', () => {
  const before = structuredClone(profiles);
  expect(validateLunarThermal(profiles)).toBe(profiles);
  expect(data).toHaveLength(768);
  expect(data.filter(r => r.grid_cells > 0)).toHaveLength(719);
  const empty = data.filter(r => r.grid_cells === 0);
  expect(empty).toHaveLength(49);
  expect(empty.every(r => r.mean_tbol_K === null && r.min_tbol_K === null && r.max_tbol_K === null)).toBe(true);
  expect(new Set(data.map(r => r.source_product)).size).toBe(384);
  expect(profiles).toEqual(before);
 });
 it('maps exactly four canonical IDs and switches site and season with all 96 bins', () => {
  const before = structuredClone(canonical);
  expect(targets.filter(t => Object.hasOwn(LUNAR_SITES, t.id))).toHaveLength(4);
  for (const [id, site] of Object.entries(LUNAR_SITES)) {
   expect(targets.find(t => t.id === id)?.name.replaceAll(' ', '_')).toBe(site);
   for (const season of ['sum', 'win'] as const) {
    const rows = selectLunarThermal(data, id, season);
    expect(rows).toHaveLength(96);
    expect(rows.map(r => r.local_time_index)).toEqual(Array.from({ length: 96 }, (_, i) => i + 1));
    expect(rows.every(r => r.site === site && r.season === season)).toBe(true);
    const summary = coverageText.trim().split('\n').find(line => line.startsWith(`${site},${season},`))!.split(',');
    expect(rows.filter(r => r.grid_cells > 0)).toHaveLength(Number(summary[3]));
    expect(rows.filter(r => r.grid_cells === 0)).toHaveLength(Number(summary[4]));
   }
  }
  expect(canonical).toEqual(before);
 });
 it('renders all empty cells unavailable and retains saved numeric precision and provenance', () => {
  let empty = 0;
  for (const id of Object.keys(LUNAR_SITES)) for (const season of ['sum', 'win'] as const) {
   const rows = selectLunarThermal(data, id, season);
   const html = renderToStaticMarkup(<LunarProfileTable rows={rows}/>);
   const count = rows.filter(r => r.grid_cells === 0).length;
   expect(html.match(/Unavailable/g)?.length ?? 0).toBe(count * 3);
   for (const row of rows) {
    expect(html).toContain(row.source_product);
    if (row.mean_tbol_K !== null) expect(html).toContain(String(row.mean_tbol_K));
   }
   empty += count;
  }
  expect(empty).toBe(49);
 });
 it('keeps all 11 nonpolar targets unavailable and thermal ranking disabled', () => {
  const nonpolar = targets.filter(t => !Object.hasOwn(LUNAR_SITES, t.id));
  expect(nonpolar).toHaveLength(11);
  for (const t of nonpolar) {
   expect(selectLunarThermal(data, t.id, 'sum')).toEqual([]);
   expect(renderToStaticMarkup(<LunarThermalObservations targetId={t.id}/>)).toContain(MOON_UNAVAILABLE);
  }
  const html = renderToStaticMarkup(<LunarThermalObservations targetId="Moon:Peary Crater"/>);
  expect(html).toContain(LUNAR_VALIDATION);
  expect(html).toContain('719 valid bins');
  expect(() => analyze()).toThrow('not integrated');
 });
 it('rejects missing, duplicated, invented or inconsistent data', () => {
  const changes = [
   (d: any[]) => d.pop(),
   (d: any[]) => d[1] = structuredClone(d[0]),
   (d: any[]) => d[0].site = 'Unknown',
   (d: any[]) => d[0].season = 'unknown',
   (d: any[]) => d[0].local_time_hour_start = 5,
   (d: any[]) => d[0].source_product = 'invented',
   (d: any[]) => d[0].mean_tbol_K = null,
   (d: any[]) => d.find(r => r.grid_cells === 0).mean_tbol_K = 0,
  ];
  for (const change of changes) {
   const copy = structuredClone(profiles); change(copy);
   expect(() => validateLunarThermal(copy)).toThrow();
  }
 });
});
describe('lunar static asset loading and retry', () => {
 beforeEach(() => vi.resetModules());
 afterEach(() => vi.unstubAllGlobals());
 it('loads only the static lunar asset and shares successful requests', async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => profiles }));
  vi.stubGlobal('fetch', fetch);
  const { loadLunarThermal } = await import('../src/services/lunarThermal');
  expect(await loadLunarThermal()).toHaveLength(768);
  await loadLunarThermal();
  expect(fetch).toHaveBeenCalledExactlyOnceWith(THERMAL_DATA_PATHS.moon);
 });
 it('reports a load failure and recovers on retry', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404 })));
  const { loadLunarThermal } = await import('../src/services/lunarThermal');
  await expect(loadLunarThermal()).rejects.toThrow('404');
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => profiles })));
  expect(await loadLunarThermal()).toHaveLength(768);
 });
 it('evicts invalid lunar content for a fresh retry', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [] })));
  const { loadLunarThermal } = await import('../src/services/lunarThermal');
  await expect(loadLunarThermal()).rejects.toThrow('768');
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => profiles })));
  expect(await loadLunarThermal()).toHaveLength(768);
 });
});

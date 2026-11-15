import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import profiles from '../public/data/thermal/lunar_polar/terratwin_moon_4_polar_profiles.json';
import { selectLunarThermal, validateLunarThermal } from '../src/services/lunarThermal';

const captured = vi.hoisted(() => ({ chart: {} as any, line: {} as any, x: {} as any, tooltip: {} as any }));
vi.mock('recharts', () => {
 const wrapper = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
 return {
  ResponsiveContainer: wrapper,
  LineChart: (props: any) => { captured.chart = props; return wrapper(props); },
  Line: (props: any) => { captured.line = props; return null; },
  XAxis: (props: any) => { captured.x = props; return null; },
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: (props: any) => { captured.tooltip = props; return null; },
 };
});
import LunarThermalChart, { lunarChartPoints } from '../src/components/LunarThermalChart';
import ThermalObservations, { MarsObservationCard } from '../src/components/ThermalObservations';
import mars from '../public/data/terratwin_mars_20_mola_themis_integrated.json';
import type { MarsThermalObservation } from '../src/types/thermal';

const data = validateLunarThermal(profiles);
describe('thermal pitch presentation', () => {
 it('uses all actual mean measurements, retaining all 49 null gaps at bin midpoints', () => {
  const before = structuredClone(data);
  const points = lunarChartPoints(data);
  expect(points).toHaveLength(768);
  expect(points.filter(p => p.mean_tbol_K === null)).toHaveLength(49);
  points.forEach((p, i) => {
   expect(p.mean_tbol_K).toBe(data[i].mean_tbol_K);
   expect(p.local_time_hour).toBe((data[i].local_time_hour_start + data[i].local_time_hour_end) / 2);
  });
  expect(data).toEqual(before);
 });
 it('updates the chart for each site and season without connecting nulls or smoothing', () => {
  for (const site of ['Peary', 'Shackleton', 'Haworth', 'Cabeus']) for (const season of ['sum', 'win'] as const) {
   const rows = selectLunarThermal(data, `Moon:${site} Crater`, season);
   const label = `${site} · ${season}`;
   const html = renderToStaticMarkup(<LunarThermalChart rows={rows} label={label}/>);
   expect(html).toContain(label);
   expect(captured.chart.data).toEqual(lunarChartPoints(rows));
   expect(captured.line.dataKey).toBe('mean_tbol_K');
   expect(captured.line.connectNulls).toBe(false);
   expect(captured.line.type).toBe('linear');
   expect(captured.line.isAnimationActive).toBe(false);
   expect(captured.x.domain).toEqual([0, 24]);
   expect(captured.chart.accessibilityLayer).toBe(true);
  }
 });
 it('shows exact stored values or unavailability in the interactive tooltip', () => {
  renderToStaticMarkup(<LunarThermalChart rows={data.slice(0, 96)} label="Cabeus summer"/>);
  for (const point of [lunarChartPoints(data)[0], lunarChartPoints(data).find(p => p.mean_tbol_K === null)!]) {
   const html = renderToStaticMarkup(captured.tooltip.content({ active: true, payload: [{ payload: point }] }));
   expect(html).toContain(point.mean_tbol_K === null ? 'Unavailable — no valid cells' : `${point.mean_tbol_K} K`);
   expect(html).toContain(point.source_product);
  }
 });
 it('shows scoped evidence summaries and keeps thermal ranking unavailable', () => {
  const html = renderToStaticMarkup(<ThermalObservations body="Moon" marsTargets={[]}/>);
  for (const text of ['Atacama · 2021', '20 targets', '4 polar Diviner sites', '768 records', '719 valid bins', '49 unavailable bins', 'Thermal analogue ranking and thermal scores are unavailable']) expect(html).toContain(text);
  expect(html).toContain('Loading diagnostic validation');
  expect(html).not.toContain('Cloud/local PASS'); // Never claim a loaded PASS while loading.
 });
 it('keeps Mars acquisition metadata visible and provenance accessible in a disclosure', () => {
  const observation = mars[0].thermal.morning as MarsThermalObservation;
  const html = renderToStaticMarkup(<MarsObservationCard phase="Morning" observation={observation}/>);
  expect(html).toContain(observation.start_time.replace('T', ' '));
  expect(html).toContain('Spatial coverage');
  expect(html).toContain('<details');
  expect(html).toContain('Observation details &amp; provenance');
  expect(html).toContain(observation.observation_id);
  expect(html).toContain(observation.url);
  expect(html).toContain(observation.processing_note);
 });
});

import { useEffect, useState } from 'react';
import LunarThermalChart from './LunarThermalChart';
import { THERMAL_DATA_PATHS } from '../config/datasets';
import { LUNAR_SITES, loadLunarThermal, selectLunarThermal, type LunarThermalBin } from '../services/lunarThermal';

export const MOON_UNAVAILABLE = 'Thermal data unavailable for this lunar target. This build contains Diviner profiles only for Peary, Shackleton, Haworth and Cabeus.';
export const LUNAR_VALIDATION = 'Saved-output consistency checks passed (zero errors). Independent source-level scientific validation is still pending.';
const temperature = (value: number | null) => value === null ? 'Unavailable' : String(value);

export function LunarProfileTable({ rows }: { rows: LunarThermalBin[] }) {
 return <div className="table-wrap thermal-table"><table>
  <caption>Diviner bolometric brightness temperature (tbol), Kelvin · 15-minute local-time bins · empty bins are not interpolated. Values retain the precision of the saved JSON.</caption>
  <thead><tr><th scope="col">Bin</th><th scope="col">Local time (h)</th><th scope="col">Mean (K)</th><th scope="col">Minimum (K)</th><th scope="col">Maximum (K)</th><th scope="col">Valid grid cells</th><th scope="col">Coverage status</th><th scope="col">Source product</th></tr></thead>
  <tbody>{rows.map(r => <tr key={r.local_time_index}><th scope="row">{r.local_time_index}</th><td>{r.local_time_hour_start}–{r.local_time_hour_end}</td><td>{temperature(r.mean_tbol_K)}</td><td>{temperature(r.min_tbol_K)}</td><td>{temperature(r.max_tbol_K)}</td><td>{r.grid_cells}</td><td>{r.coverage_status === 'NO_VALID_CELLS' ? 'No valid cells' : 'Has valid cells'}</td><td>{r.source_product}</td></tr>)}</tbody>
 </table></div>;
}
export default function LunarThermalObservations({ targetId }: { targetId?: string }) {
 const [data, setData] = useState<LunarThermalBin[]>();
 const [error, setError] = useState('');
 const [retry, setRetry] = useState(0);
 const [season, setSeason] = useState<'sum' | 'win'>('sum');
 const available = !!targetId && Object.hasOwn(LUNAR_SITES, targetId);
 useEffect(() => {
  if (!available) return;
  let current = true;
  setData(undefined); setError('');
  loadLunarThermal().then(rows => { if (current) setData(rows); }).catch(e => { if (current) setError(e instanceof Error ? e.message : 'Lunar thermal asset could not be loaded.'); });
  return () => { current = false; };
 }, [available, retry]);
 if (!available) return <div className="thermal-message" role="status"><p>{MOON_UNAVAILABLE}</p></div>;
 const rows = data ? selectLunarThermal(data, targetId!, season) : [];
 return <>
  <div className="thermal-message"><p><strong>{LUNAR_VALIDATION}</strong></p><p>Extraction audit: 384 source products · 4 polar sites · 2 seasons · 96 bins per season and site · 768 site-level records · 719 valid bins · 49 empty bins.</p><p>These are seasonal gridded profiles, not individual dated observations or validated thermal suitability scores. Valid-cell counts describe available sampling, not area coverage percentages or measurement accuracy.</p></div>
  {error ? <div className="thermal-message" role="alert"><p>{error}</p><button className="secondary" onClick={() => setRetry(n => n + 1)}>Retry lunar thermal asset</button></div> : !data ? <p className="thermal-message" role="status">Loading lunar Diviner profiles…</p> : <>
   <div className="thermal-message"><label className="field-label" htmlFor="lunar-season">Season (source label)</label><div className="select-wrap"><select id="lunar-season" value={season} onChange={e => setSeason(e.target.value as 'sum' | 'win')}><option value="sum">Summer (sum)</option><option value="win">Winter (win)</option></select></div><p>Selected site and season: {rows.length} bins · {rows.filter(r => r.grid_cells > 0).length} valid · {rows.filter(r => r.grid_cells === 0).length} unavailable.</p></div>
   <LunarThermalChart rows={rows} label={`${targetId!.replace('Moon:', '')} · ${season === 'sum' ? 'Summer (sum)' : 'Winter (win)'}`}/>
   <details className="thermal-periods"><summary>Full 96-bin measurements and source products</summary><LunarProfileTable rows={rows}/></details>
  </>}
  <details className="thermal-periods"><summary>Extraction provenance and saved outputs</summary><div className="thermal-message"><p>Lunar Diviner polar seasonal average tbol products. Source identifiers encode polar hemisphere (poln/pols), season (sum/win), local-time bin and product suffix 240. Individual product identifiers are preserved in the table. Acquisition dates and extraction footprint geometry are not supplied in this bundle.</p><p>Step 27 saved-output consistency audit passed. All three bundle payload SHA256 checksums and byte counts were verified against the manifest before integration. This is a saved-output integrity check; independent source-level scientific validation remains pending.</p><p><a href={THERMAL_DATA_PATHS.moon} target="_blank" rel="noreferrer">Unmodified profiles JSON ↗</a> · <a href={THERMAL_DATA_PATHS.moonManifest} target="_blank" rel="noreferrer">Manifest and SHA256 checksums ↗</a> · <a href={THERMAL_DATA_PATHS.moonCoverage} target="_blank" rel="noreferrer">Coverage summary CSV ↗</a> · <a href={THERMAL_DATA_PATHS.moonCsv} target="_blank" rel="noreferrer">Profiles CSV ↗</a></p></div></details>
 </>;
}

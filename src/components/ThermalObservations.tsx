import { useEffect, useState } from 'react';
import LunarThermalObservations from './LunarThermalObservations';
import { Globe2, Info, ShieldAlert, Thermometer } from 'lucide-react';
import { EARTH_METRICS, loadEarthThermal, loadMarsThermal, selectMarsThermal } from '../services/thermalDatasets';
import { THERMAL_DATA_PATHS } from '../config/datasets';
import type { PlanetaryBody, PlanetaryTarget, Terrain } from '../types';
import type { EarthThermalEvidence, MarsThermalObservation, MarsThermalTarget } from '../types/thermal';

export function thermalNumber(value: unknown, digits = 2): string {
 return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US', { maximumFractionDigits: digits }) : 'Unavailable';
}
type Resource<T> = { data?: T; error?: string; loading: boolean };
function Failure({ message, retry }: { message: string; retry: () => void }) {
 return <div className="thermal-message" role="alert"><ShieldAlert size={20}/><p>{message}</p><button className="secondary" onClick={retry}>Retry thermal assets</button></div>;
}

export function MarsObservationCard({ phase, observation }: { phase: string; observation: MarsThermalObservation | null }) {
 if (!observation) return <article className="thermal-observation"><h4>{phase}</h4><p>Observation unavailable. No substitute measurement is used.</p></article>;
 const value = (n: unknown, suffix: string, digits = 2) => `${thermalNumber(n, digits)}${typeof n === 'number' && Number.isFinite(n) ? suffix : ''}`;
 return <article className="thermal-observation">
  <h4>{phase}</h4><p className="thermal-temperature">{value(observation.mean_k, ' K')}<small>Spatial mean brightness temperature</small></p>
  <dl className="thermal-facts">
   <div><dt>Minimum / maximum</dt><dd>{value(observation.min_k, ' K')} / {value(observation.max_k, ' K')}</dd></div>
   <div><dt>Acquired (source timestamp)</dt><dd>{observation.start_time.replace('T', ' ')}</dd></div>
   <div><dt>Reported local time</dt><dd>{value(observation.local_time, ' h', 3)}</dd></div>
   <div><dt>Solar longitude</dt><dd>{value(observation.solar_longitude, '°', 3)}</dd></div>
   <div><dt>Spatial coverage</dt><dd>{value(typeof observation.coverage === 'number' ? observation.coverage * 100 : undefined, '%')}</dd></div>
   <div><dt>Observation ID</dt><dd>{observation.observation_id}</dd></div>
   <div><dt>Source product</dt><dd>{observation.measurement_type}</dd></div>
   <div><dt>Sampling footprint</dt><dd>{observation.spatial_coverage_note || (typeof observation.sampling_radius_km === 'number' ? `${observation.sampling_radius_km} km radius` : 'Unavailable')}</dd></div>
   <div><dt>Processing status</dt><dd>{observation.projection_validation.replaceAll('_', ' ')}</dd></div>
  </dl>
  <p>{observation.processing_note}</p>
  <a className="secondary" href={observation.url} target="_blank" rel="noreferrer">THEMIS/PDS source product ↗</a>
 </article>;
}

interface Props { body: PlanetaryBody; target?: PlanetaryTarget; marsTargets: PlanetaryTarget[]; earthSite?: Terrain }
export default function ThermalObservations({ body, target, marsTargets, earthSite }: Props) {
 const [earth, setEarth] = useState<Resource<EarthThermalEvidence>>({ loading: true });
 const [mars, setMars] = useState<Resource<MarsThermalTarget[]>>({ loading: true });
 const [retry, setRetry] = useState(0);
 const [period, setPeriod] = useState('2021');
 useEffect(() => {
  let current = true;
  setEarth({ loading: true }); setMars({ loading: true });
  if (!earthSite) setEarth({ loading: false, error: 'Canonical Atacama site (Earth ID 24) is unavailable.' });
  else loadEarthThermal(earthSite).then(data => { if (current) setEarth({ loading: false, data }); }).catch(error => { if (current) setEarth({ loading: false, error: error instanceof Error ? error.message : 'Earth thermal evidence could not be loaded.' }); });
  loadMarsThermal(marsTargets).then(data => { if (current) setMars({ loading: false, data }); }).catch(error => { if (current) setMars({ loading: false, error: error instanceof Error ? error.message : 'Mars thermal evidence could not be loaded.' }); });
  return () => { current = false; };
 }, [earthSite, marsTargets, retry]);
 const chosen = earth.data?.records.find(r => r.period === period);
 const marsTarget = target && mars.data ? selectMarsThermal(mars.data, target.id) : undefined;
 const retryAssets = () => setRetry(value => value + 1);
 return <div className="thermal-evidence">
  <div className="demo-banner"><Info size={20}/><div><p><strong>Thermal observations · read-only evidence.</strong> Thermal analogue ranking and thermal scores are unavailable.</p><p>Earth diagnostics and planetary measurements have different definitions. Diagnostic equivalence does not establish thermal suitability. Atacama is a fixed demonstration site, not a selected thermal analogue.</p></div></div>

  <section className="comparison" aria-labelledby="planetary-thermal-heading">
   <div className="panel-heading"><div><h4 id="planetary-thermal-heading"><Thermometer size={18}/> {body} · {target?.name || 'Target unavailable'}</h4><p>{body === 'Mars' ? '20 precomputed targets · use the planetary selector to switch sites' : '15 canonical targets · 4 polar thermal profiles · 11 thermal datasets unavailable'}</p></div><span className="tag">{body === 'Mars' ? 'PRELIMINARY' : 'SOURCE VALIDATION PENDING'}</span></div>
   {body === 'Moon' ? <LunarThermalObservations targetId={target?.id}/> : <>
    <div className="explanation"><Info size={18}/><p><strong>Unpaired observations.</strong> Morning and evening observations are not same-day pairs and cannot be used to calculate a validated diurnal temperature difference. Scientific validation is preliminary. Coverage labels do not establish measurement accuracy or mission suitability.</p></div>
    {mars.loading ? <p className="thermal-message" role="status">Loading Mars observation evidence…</p> : mars.error ? <Failure message={mars.error} retry={retryAssets}/> : marsTarget ? <div className="thermal-observation-grid"><MarsObservationCard phase="Morning" observation={marsTarget.morning}/><MarsObservationCard phase="Evening" observation={marsTarget.evening}/></div> : <p className="thermal-message" role="status">No thermal observations match this canonical target. No other target has been substituted.</p>}
   </>}
  </section>

  <section className="comparison" aria-labelledby="earth-thermal-heading">
   <div className="panel-heading"><div><h4 id="earth-thermal-heading"><Globe2 size={18}/> Earth · Atacama_3_3 · 2021</h4><p>Canonical ID 24 · one site-year · observation availability and quality diagnostics</p></div></div>
   {earth.loading ? <p className="thermal-message" role="status">Loading validated Earth diagnostics…</p> : earth.error ? <Failure message={earth.error} retry={retryAssets}/> : earth.data && chosen ? <>
    <div className="thermal-message"><p><strong>Cloud/local diagnostic equivalence: {earth.data.validation.conclusion}</strong></p><p>{thermalNumber(earth.data.validation.matching_fields, 0)} matching fields · zero numerical discrepancies across {thermalNumber(earth.data.validation.numeric_comparisons, 0)} numeric comparisons · 12 months + 1 yearly summary.</p><p>Recorded processing validation, not scientific thermal suitability. No representative temperatures or day–night contrasts are contained in this artifact.</p></div>
    <div className="explanation"><ShieldAlert size={18}/><p><strong>Zero strict-night eligibility.</strong> Masked nighttime QC means unknown quality, not good or bad quality. Strict-night QA + window eligibility is zero throughout 2021. QA rules, phase windows, and coverage screens remain provisional and unchanged.</p></div>
    <div className="thermal-message"><label className="field-label" htmlFor="thermal-period">Inspect diagnostic period</label><div className="select-wrap"><select id="thermal-period" value={period} onChange={event => setPeriod(event.target.value)}>{[...earth.data.records].sort((a,b) => a.period.localeCompare(b.period)).map(r => <option key={r.period} value={r.period}>{r.period}{r.period_type === 'year' ? ' — yearly summary' : ''}</option>)}</select></div><p>{thermalNumber(chosen.source_product_dates, 0)} source product dates / {thermalNumber(chosen.calendar_dates, 0)} calendar dates · {thermalNumber(chosen.native_centres, 0)} native centres · {thermalNumber(chosen.pixel_date_records, 0)} pixel-date records.</p></div>
    <div className="table-wrap thermal-table"><table><caption>{chosen.period} · pixel-date diagnostics, not independent observations</caption><thead><tr><th scope="col">Diagnostic</th><th scope="col">Day [13,15) h</th><th scope="col">Night [1,3) h</th></tr></thead><tbody>{EARTH_METRICS.map(([key,label]) => <tr key={key}><th scope="row">{label}</th><td>{thermalNumber(chosen[`day__${key}__pixels`],0)}</td><td>{thermalNumber(chosen[`night__${key}__pixels`],0)}</td></tr>)}</tbody></table></div>
    <div className="thermal-message"><p>Source: {chosen.dataset_id} · 5 km geodesic radius · {chosen.native_grid} · native-centre inclusion.</p><p>For {chosen.period}: day strict + window over ≥80% sampled cell area on {thermalNumber(chosen.day__supported_dates,0)} dates ({thermalNumber(typeof chosen.day__supported_calendar_fraction === 'number' ? chosen.day__supported_calendar_fraction * 100 : undefined)}% of calendar dates); night on {thermalNumber(chosen.night__supported_dates,0)} dates ({thermalNumber(typeof chosen.night__supported_calendar_fraction === 'number' ? chosen.night__supported_calendar_fraction * 100 : undefined)}%). This reports the existing provisional coverage screen.</p></div>
    <details className="thermal-periods" open><summary>All 12 monthly diagnostics and the yearly summary</summary><div className="table-wrap thermal-table"><table><caption>Distinct product dates are counted once, regardless of how many pixels pass</caption><thead><tr><th scope="col">Period</th><th scope="col">Source dates / calendar</th><th scope="col">Day valid-LST dates</th><th scope="col">Night valid-LST dates</th><th scope="col">Night strict + window dates</th><th scope="col">Night relaxed + window dates</th></tr></thead><tbody>{earth.data.records.map(r => <tr key={r.period}><th scope="row">{r.period}{r.period_type === 'year' ? ' (year)' : ''}</th><td>{r.source_product_dates} / {r.calendar_dates}</td><td>{thermalNumber(r.day__lst_valid__dates,0)}</td><td>{thermalNumber(r.night__lst_valid__dates,0)}</td><td>{thermalNumber(r.night__strict_qa_in_phase__dates,0)}</td><td>{thermalNumber(r.night__relaxed_qa_in_phase__dates,0)}</td></tr>)}</tbody></table></div></details>
    <details className="thermal-periods"><summary>Source files and processing provenance</summary><div className="thermal-message"><p>Run: {chosen.run_id}</p><p>Catalogue SHA-256: {chosen.catalog_sha256}</p><p>Configuration SHA-256: {chosen.config_sha256}</p><p><a href={THERMAL_DATA_PATHS.earth} target="_blank" rel="noreferrer">Unmodified compact diagnostic JSON ↗</a> · <a href={THERMAL_DATA_PATHS.earthValidation} target="_blank" rel="noreferrer">Recorded validation report ↗</a></p></div></details>
   </> : null}
  </section>
 </div>;
}

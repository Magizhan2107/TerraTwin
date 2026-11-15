import { invalidateThermalAsset, loadJson } from './thermalDatasets';
import { THERMAL_DATA_PATHS } from '../config/datasets';

// Explicit aliases retain the canonical IDs; the thermal asset never supplies terrain.
export const LUNAR_SITES: Record<string, string> = {
 'Moon:Peary Crater': 'Peary_Crater',
 'Moon:Shackleton Crater': 'Shackleton_Crater',
 'Moon:Haworth Crater': 'Haworth_Crater',
 'Moon:Cabeus Crater': 'Cabeus_Crater',
};
export interface LunarThermalBin {
 site: string; hemisphere: 'poln' | 'pols'; season: 'sum' | 'win';
 local_time_index: number; local_time_hour_start: number; local_time_hour_end: number;
 grid_cells: number; mean_tbol_K: number | null; min_tbol_K: number | null; max_tbol_K: number | null;
 coverage_status: 'HAS_VALID_CELLS' | 'NO_VALID_CELLS'; source_product: string;
}
export function validateLunarThermal(data: unknown): LunarThermalBin[] {
 if (!Array.isArray(data) || data.length !== 768) throw new Error('Lunar thermal asset must contain all 768 site-level bins.');
 const seen = new Set<string>();
 let empty = 0;
 for (const r of data) {
  if (!r || !Object.values(LUNAR_SITES).includes(r.site) || !['sum', 'win'].includes(r.season) || !Number.isInteger(r.local_time_index) || r.local_time_index < 1 || r.local_time_index > 96) throw new Error('Unknown lunar site, season or local-time bin.');
  const key = `${r.site}:${r.season}:${r.local_time_index}`;
  if (seen.has(key)) throw new Error('Duplicate lunar thermal bin.');
  seen.add(key);
  const hemisphere = r.site === 'Peary_Crater' ? 'poln' : 'pols';
  if (r.hemisphere !== hemisphere || r.local_time_hour_start !== (r.local_time_index - 1) / 4 || r.local_time_hour_end !== r.local_time_index / 4 || r.source_product !== `pcp_avg_tbol_${hemisphere}_${r.season}_ltim${String(r.local_time_index).padStart(2, '0')}_240`) throw new Error('Lunar time-bin or source provenance is inconsistent.');
  if (!Number.isInteger(r.grid_cells) || r.grid_cells < 0) throw new Error('Invalid lunar valid-cell count.');
  const temperatures = [r.min_tbol_K, r.mean_tbol_K, r.max_tbol_K];
  if (r.grid_cells === 0) {
   empty++;
   if (r.coverage_status !== 'NO_VALID_CELLS' || temperatures.some(v => v !== null)) throw new Error('Empty lunar bins must retain null measurements.');
  } else if (r.coverage_status !== 'HAS_VALID_CELLS' || temperatures.some(v => typeof v !== 'number' || !Number.isFinite(v)) || r.min_tbol_K > r.mean_tbol_K || r.mean_tbol_K > r.max_tbol_K) throw new Error('Invalid lunar temperature cells.');
 }
 if (empty !== 49 || new Set(data.map(r => r.source_product)).size !== 384) throw new Error('Lunar coverage differs from the saved-output audit.');
 return data as LunarThermalBin[];
}
export function selectLunarThermal(data: LunarThermalBin[], targetId: string, season: 'sum' | 'win') {
 const site = LUNAR_SITES[targetId];
 return data.filter(r => r.site === site && r.season === season).sort((a, b) => a.local_time_index - b.local_time_index);
}
export async function loadLunarThermal(): Promise<LunarThermalBin[]> {
 try { return validateLunarThermal(await loadJson(THERMAL_DATA_PATHS.moon)); }
 catch (error) { invalidateThermalAsset(THERMAL_DATA_PATHS.moon); throw error; }
}

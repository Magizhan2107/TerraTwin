import type { ScientificModule, AnalysisResult } from '../../types';
export interface ModuleDataset { targetId: string; provenance: string; measurements: Record<string, number> }
export const integration = { id: 'thermalTesting', status: 'unavailable', requiredData: 'temperature range, seasonal sampling, surface properties and measurement units' } as const;
// Observation presentation is separate from the scientific ranking adapter.
export const observations = { status: 'preliminary', ranking: 'unavailable' } as const;
// Teammates implement this contract with validated measurements and documented scoring.
export type ModuleAdapter = ScientificModule<ModuleDataset>;
export function analyze(): AnalysisResult[] { throw new Error('Validated thermalTesting data and scoring are not integrated.'); }

export type ModuleId = 'roverMobility' | 'thermalTesting' | 'dustSolar';
export type PlanetaryBody = 'Mars' | 'Moon';
export interface Provenance { source: string; demonstration: boolean; metadata?: Readonly<Record<string, unknown>> }
export interface Terrain { planet?: PlanetaryBody | 'Earth'; id: string; name: string; latitude: number; longitude: number; mean_slope_deg: number; p90_slope_deg: number; roughness_mean_m: number; elevation_stddev_m: number }
export interface FeatureComparison { key: string; label: string; unit: string; target: number; candidate: number; difference: number; normalizedDifference: number }
export interface AnalysisResult { moduleId: ModuleId; planetaryTarget: { id: string; body: 'Mars' | 'Moon'; name: string }; earthCandidateId: string; name: string; coordinates: { latitude: number; longitude: number }; similarityScore: number; featureComparisons: FeatureComparison[]; scientificLimitations: string[]; dataProvenance: Provenance[] }
export interface ScientificModule<T> { id: ModuleId; analyze: (target: T, candidates: T[]) => AnalysisResult[] }
export interface Dataset { target: Terrain; candidates: Terrain[]; excluded: number; provenance: Provenance[] }

export interface PlanetaryTarget extends Terrain {
 planet: PlanetaryBody;
 metadata: Readonly<Record<string, unknown>>;
}
export interface TargetCatalog {
 targets: PlanetaryTarget[];
 rejected: { id: string; name: string; error: string }[];
 error?: string;
}
export interface EarthDataset { candidates: Terrain[]; excluded: number; provenance: Provenance[] }
export interface PlanetaryDatasets { earth: EarthDataset; planets: Record<PlanetaryBody, TargetCatalog> }

import type { Terrain, AnalysisResult, Provenance } from '../../types';
import { LIMITATIONS } from '../../config/datasets';
// Fixed engineering scales, chosen for this preliminary MVP. Equal weights.
// These are transparent design parameters, not empirically calibrated thresholds.
export const FEATURES = [
 { key: 'mean_slope_deg', label: 'Mean slope', unit: '°', scale: 30 },
 { key: 'p90_slope_deg', label: '90th percentile slope', unit: '°', scale: 45 },
 { key: 'roughness_mean_m', label: 'Mean roughness', unit: 'm', scale: 100 },
 { key: 'elevation_stddev_m', label: 'Elevation variation', unit: 'm', scale: 1000 },
] as const;
export function scoreTerrain(target: Terrain, candidate: Terrain, provenance: Provenance[] = []): AnalysisResult {
 const featureComparisons = FEATURES.map(f => ({ key: f.key, label: f.label, unit: f.unit, target: target[f.key], candidate: candidate[f.key], difference: candidate[f.key] - target[f.key], normalizedDifference: Math.min(Math.abs(candidate[f.key] - target[f.key]) / f.scale, 1) }));
 const similarityScore = 100 * (1 - featureComparisons.reduce((sum, f) => sum + f.normalizedDifference, 0) / FEATURES.length);
 return { moduleId: 'roverMobility', planetaryTarget: { id: target.id, body: target.planet === 'Moon' ? 'Moon' : 'Mars', name: target.name }, earthCandidateId: candidate.id, name: candidate.name, coordinates: { latitude: candidate.latitude, longitude: candidate.longitude }, similarityScore, featureComparisons, scientificLimitations: LIMITATIONS, dataProvenance: provenance };
}
export function rankCandidates(target: Terrain, candidates: Terrain[], provenance: Provenance[] = []) {
 return candidates.map(candidate => scoreTerrain(target, candidate, provenance)).sort((a,b) => b.similarityScore - a.similarityScore || a.earthCandidateId.localeCompare(b.earthCandidateId));
}

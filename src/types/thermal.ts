import type { PlanetaryTarget } from './index';

export interface EarthThermalPeriod {
 schema_version: 'earth-thermal-cloud/1.0.0';
 location_id: string; name: string; planet: 'Earth'; period: string; period_type: 'month' | 'year';
 canonical_latitude: number; canonical_longitude: number; run_id: string; dataset_id: string;
 calendar_dates: number; source_product_dates: number; native_centres: number; pixel_date_records: number;
 footprint_radius_m: number; native_grid: string; config_sha256: string; catalog_sha256: string;
 status: string; mission_suitability: 'not_assessed';
 [field: string]: unknown;
}
export interface EarthThermalValidation {
 conclusion: 'PASS'; periods: number; matching_fields: number; numeric_comparisons: number;
 numerical_differences: unknown[]; missing_fields: number; missing_records: number;
 unexpected_fields: number; mismatched_fields: number; unverified_fields: number;
}
export interface EarthThermalEvidence {
 records: EarthThermalPeriod[]; validation: EarthThermalValidation;
}
export interface MarsThermalObservation {
 mean_k?: number | null; min_k?: number | null; max_k?: number | null;
 observation_id: string; start_time: string; local_time?: number | null;
 coverage?: number | null; solar_longitude?: number | null;
 temperature_unit: 'K'; measurement_type: string; quality_flag: string;
 sampling_radius_km: number | null; spatial_coverage_note: string | null;
 processing_note: string; projection_validation: string; url: string;
 same_day_diurnal_pair: false;
 [field: string]: unknown;
}
export interface MarsThermalTarget {
 target: PlanetaryTarget;
 morning: MarsThermalObservation | null;
 evening: MarsThermalObservation | null;
}

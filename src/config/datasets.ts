export const DATA_PATHS = { mars: `${import.meta.env.BASE_URL}data/terratwin_mars_20_targets_harmonized.json`, moon: `${import.meta.env.BASE_URL}data/terratwin_moon_15_targets_harmonized.json`, earth: `${import.meta.env.BASE_URL}data/earth_terrain_harmonized.geojson` };
export const THERMAL_DATA_PATHS = {
 moon: `${import.meta.env.BASE_URL}data/thermal/lunar_polar/terratwin_moon_4_polar_profiles.json`,
 moonManifest: `${import.meta.env.BASE_URL}data/thermal/lunar_polar/manifest.json`,
 moonCoverage: `${import.meta.env.BASE_URL}data/thermal/lunar_polar/polar_coverage_summary.csv`,
 moonCsv: `${import.meta.env.BASE_URL}data/thermal/lunar_polar/terratwin_moon_4_polar_profiles.csv`,
 earth: `${import.meta.env.BASE_URL}data/thermal/earth_atacama_2021_availability.json`,
 earthValidation: `${import.meta.env.BASE_URL}data/thermal/earth_atacama_2021_validation.json`,
 mars: `${import.meta.env.BASE_URL}data/terratwin_mars_20_mola_themis_integrated.json`,
};
export const LIMITATIONS = [ 'Earth gravity differs from Mars and Moon gravity.', 'Atmospheric pressure, composition and weather differ.', 'Terrain similarity does not establish rover safety.', 'MOLA terrain resolution cannot resolve small obstacles.', 'Soil mechanics and dust behavior require additional data.', 'Rankings only cover locations in the Earth candidate database.' ];

export const TERRAIN_COMPATIBILITY_NOTE = 'Preliminary terrain-based analogue estimates. Scores indicate similarity across selected terrain metrics. Mission suitability remains unconfirmed. The 463 m output grid and 5 km radius do not establish equal source resolution or accuracy. Bilinear resampling adds no terrain detail. Georeferencing and equivalent slope, 3×3 roughness and elevation-variation definitions require independent verification.';

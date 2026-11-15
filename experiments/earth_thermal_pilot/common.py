"""Offline catalogue, configuration and MODIS interpretation. No Earth Engine import."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

PILOT_DIR = Path(__file__).resolve().parent
REPO_DIR = PILOT_DIR.parents[1]
PILOT_LOCATIONS = {
    "24": "Atacama_3_3", "73": "Death_Valley_3_3", "122": "Hawaii_3_3",
    "220": "Namib_Desert_3_3", "269": "Ladakh_3_3", "318": "Salar_de_Uyuni_3_3",
    "367": "Tenerife_3_3", "465": "Gobi_Desert_3_3", "661": "Patagonian_Steppe_3_3",
    "710": "Danakil_Depression_3_3",
}
DATASET = "MODIS/061/MYD11A1"
BANDS = [
    "LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night",
    "Day_view_time", "Night_view_time", "Day_view_angle", "Night_view_angle",
    "Clear_day_cov", "Clear_night_cov",
]
STAGES = [
    "lst_valid", "qc_present", "mandatory_produced", "mandatory_good",
    "data_quality_good", "emissivity_error_le_0_01", "lst_error_le_1k",
    "time_valid", "phase_window", "strict_qa", "relaxed_qa", "strict_qa_with_time", "relaxed_qa_with_time",
    "strict_qa_in_phase", "relaxed_qa_in_phase",
]
QA_FIELDS = ["mandatory", "data_quality", "emissivity_error", "lst_error"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config(path: Path | None = None) -> dict:
    path = (path or PILOT_DIR / "config.json").resolve()
    config = json.loads(path.read_text())
    if config.get("dataset_id") != DATASET:
        raise ValueError("This pilot supports only MYD11A1 Collection 6.1.")
    ids = config.get("location_ids")
    if not isinstance(ids, list) or len(ids) != 10 or set(ids) != set(PILOT_LOCATIONS):
        raise ValueError("Configuration must retain the exact ten canonical string IDs.")
    if config.get("start_date") != "2021-01-01" or config.get("end_date_exclusive") != "2024-01-01":
        raise ValueError("This availability pilot is restricted to 2021–2023.")
    if config.get("footprint_radius_m") != 5000:
        raise ValueError("The requested footprint is a 5,000 m radius circle.")
    if config.get("threshold_status") != "provisional_diagnostic_only":
        raise ValueError("Pilot thresholds must remain provisional.")
    for phase in ["day", "night"]:
        window = config["phase_windows_hours"][phase]
        if len(window) != 2 or any(type(x) not in (int, float) or not 0 <= x <= 24 for x in window) or window[0] % 24 == window[1] % 24:
            raise ValueError("Phase intervals must be nonempty local-hour intervals.")
    thresholds = config["exploratory_monthly_thresholds"]
    if type(thresholds["strict_qa_phase_dates_min"]) is not int or thresholds["strict_qa_phase_dates_min"] < 0:
        raise ValueError("Date threshold must be a nonnegative integer.")
    for name in ["strict_qa_phase_date_fraction_min", "same_product_date_spatial_support_fraction_min"]:
        if type(thresholds[name]) not in (int, float) or not 0 <= thresholds[name] <= 1:
            raise ValueError("Coverage thresholds must be fractions.")
    if not 1 <= config["export_tile_scale"] <= 16 or config["masked_sentinel"] != -9999 or config["geometry_max_error_m"] <= 0:
        raise ValueError("Invalid export configuration.")
    return config


def load_locations(config: dict) -> tuple[Path, list[dict]]:
    path = (PILOT_DIR / config["canonical_geojson"]).resolve()
    expected = REPO_DIR / "public/data/earth_terrain_harmonized.geojson"
    if path != expected:
        raise ValueError("Pilot coordinates must come from the existing canonical GeoJSON.")
    data = json.loads(path.read_text())
    if data.get("type") != "FeatureCollection":
        raise ValueError("Canonical Earth data must be a FeatureCollection.")
    accepted = {}
    metrics = ["mean_slope_deg", "p90_slope_deg", "roughness_mean_m", "elevation_stddev_m"]
    for index, feature in enumerate(data["features"]):
        p = feature.get("properties")
        if feature.get("type") != "Feature" or not isinstance(p, dict):
            continue
        values = [p.get(key) for key in metrics + ["latitude", "longitude"]]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            continue
        if abs(p["latitude"]) > 90 or abs(p["longitude"]) > 180 or any(p[key] < 0 for key in metrics):
            continue
        if p["mean_slope_deg"] > 90 or p["p90_slope_deg"] > 90 or p["p90_slope_deg"] < p["mean_slope_deg"]:
            continue
        location_id = str(p.get("id", feature.get("id", f"candidate-{index + 1}")))
        if location_id not in accepted:
            accepted[location_id] = p
    if len(accepted) != 731:
        raise ValueError(f"Canonical acceptance changed: expected 731, found {len(accepted)}. Investigate before extraction.")
    locations = []
    for location_id in config["location_ids"]:
        p = accepted.get(location_id)
        if not p or p.get("name") != PILOT_LOCATIONS[location_id]:
            raise ValueError(f"Missing or mismatched canonical location {location_id}.")
        locations.append({"location_id": location_id, "name": p["name"],
                          "canonical_latitude": p["latitude"], "canonical_longitude": p["longitude"]})
    return path, locations


def within_pilot(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(PILOT_DIR):
        raise ValueError("Pilot outputs must stay inside experiments/earth_thermal_pilot/.")
    return path


def write_json(path: Path, value: object) -> None:
    path = within_pilot(path)
    if path.exists():
        raise ValueError(f"Output already exists: {path}. Choose a fresh output path.")
    payload = json.dumps(value, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(payload)


def decode_time(raw: int | None) -> float | None:
    """Raw 0..240, scale 0.1 local solar hour. Preserve raw DN separately."""
    if type(raw) is not int or not 0 <= raw <= 240:
        return None
    return (raw / 10) % 24


def in_window(hour: float | None, window: list[float]) -> bool:
    if hour is None:
        return False
    start, end = (value % 24 for value in window)
    return start <= hour < end if start < end else hour >= start or hour < end


def decode_qa(raw: int | None) -> dict | None:
    if type(raw) is not int or not 0 <= raw <= 255:
        return None
    return {name: (raw >> (index * 2)) & 3 for index, name in enumerate(QA_FIELDS)}


def classify_pixel(lst: int | None, qc: int | None, time: int | None, window: list[float]) -> tuple[dict, dict | None, float | None]:
    available = type(lst) is int and 7500 <= lst <= 65535
    qa = decode_qa(qc) if available else None
    hour = decode_time(time) if available else None
    strict = qa is not None and all(value == 0 for value in qa.values())
    relaxed = qa is not None and qa["mandatory"] <= 1 and qa["data_quality"] == 0 and qa["emissivity_error"] <= 1 and qa["lst_error"] <= 1
    phase = in_window(hour, window)
    stages = {
        "lst_valid": available,
        "qc_present": qa is not None,
        "mandatory_produced": qa is not None and qa["mandatory"] <= 1,
        "mandatory_good": qa is not None and qa["mandatory"] == 0,
        "data_quality_good": qa is not None and qa["data_quality"] == 0,
        "emissivity_error_le_0_01": qa is not None and qa["emissivity_error"] == 0,
        "lst_error_le_1k": qa is not None and qa["lst_error"] == 0,
        "time_valid": hour is not None,
        "phase_window": phase,
        "strict_qa": strict,
        "relaxed_qa": relaxed,
        "strict_qa_with_time": strict and hour is not None,
        "relaxed_qa_with_time": relaxed and hour is not None,
        "strict_qa_in_phase": strict and phase,
        "relaxed_qa_in_phase": relaxed and phase,
    }
    return stages, qa, hour


def dates_in_year(year: int) -> list[str]:
    start = dt.date(year, 1, 1)
    return [(start + dt.timedelta(days=index)).isoformat() for index in range((dt.date(year + 1, 1, 1) - start).days)]

"""Offline, fail-closed validation and summaries of downloaded batch CSV files."""
from __future__ import annotations

from collections import Counter
import csv
import datetime as dt
import math
from pathlib import Path

from common import (BANDS, DATASET, QA_FIELDS, STAGES, classify_pixel, dates_in_year,
                    digest, load_locations, PILOT_DIR)
from ee_export import COLUMNS


def integer(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid numeric field {field}: {value!r}") from None
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"Nonfinite or noninteger field {field}.")
    return int(number)



def pixel_key_coordinate(value, field):
    """Match raw/1.0.0 inventory %.0f labels, not zero-based cell indices.

    Sampled centres can be n+0.5. Only the integer/half-integer lattice
    is accepted; half ties go away from zero, unlike Python round().
    The complete daily key set must still match the exported inventory.
    """
    number = finite(value, field)
    if number.is_integer():
        return int(number)
    if abs(number) % 1 != 0.5:
        raise ValueError(f"Invalid fractional pixel coordinate {field}.")
    return math.floor(number + 0.5) if number > 0 else math.ceil(number - 0.5)


def finite(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid numeric field {field}.") from None
    if not math.isfinite(number):
        raise ValueError(f"Nonfinite field {field}.")
    return number


def read_exports(paths: list[Path], config: dict, config_hash: str, run_id: str) -> tuple[dict, str]:
    catalog, locations = load_locations(config)
    catalog_hash = digest(catalog)
    lookup = {location["location_id"]: location for location in locations}
    partitions = {}
    for path in paths:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not set(COLUMNS).issubset(reader.fieldnames):
                raise ValueError(f"Missing raw export columns in {path}.")
            for row in reader:
                if row["schema_version"] != "earth-thermal-availability-raw/1.0.0" or row["dataset_id"] != DATASET:
                    raise ValueError("Unknown raw export version/dataset.")
                if row["run_id"] != run_id or row["catalog_sha256"] != catalog_hash or row["config_sha256"] != config_hash:
                    raise ValueError("Run, catalogue or configuration fingerprint mismatch.")
                location_id = row["location_id"]
                location = lookup.get(location_id)
                if location is None or row["name"] != location["name"]:
                    raise ValueError(f"Unknown or mismatched canonical ID {location_id!r}.")
                for field in ["canonical_latitude", "canonical_longitude"]:
                    if not math.isclose(finite(row[field], field), location[field], rel_tol=0, abs_tol=1e-12):
                        raise ValueError(f"Coordinate mismatch for {location_id}.")
                year = integer(row["year"], "year")
                if year not in (2021, 2022, 2023) or integer(row["footprint_radius_m"], "radius") != 5000:
                    raise ValueError("Unexpected year or footprint.")
                partition = partitions.setdefault((location_id, year), {"inventory": None, "days": {}})
                if row["record_type"] == "partition_inventory":
                    if partition["inventory"] is not None:
                        raise ValueError("Duplicate partition inventory. Do not import the same export twice.")
                    partition["inventory"] = row
                elif row["record_type"] == "pixel":
                    date = dt.date.fromisoformat(row["product_date_utc"])
                    if date.year != year or not row["image_id"]:
                        raise ValueError("Invalid product date/image ID.")
                    x, y = (finite(row[field], field) for field in ("pixel_x", "pixel_y"))
                    convention = (x % 1, y % 1)
                    if convention not in ((0.0, 0.0), (0.5, 0.5)):
                        raise ValueError("Invalid or mixed pixel-coordinate lattice.")
                    if partition.setdefault("coordinate_convention", convention) != convention:
                        raise ValueError("Pixel-coordinate convention changed within partition.")
                    key = (pixel_key_coordinate(x, "pixel_x"), pixel_key_coordinate(y, "pixel_y"))
                    day = partition["days"].setdefault(date.isoformat(), {"image_id": row["image_id"], "pixels": {}})
                    if day["image_id"] != row["image_id"]:
                        raise ValueError("Multiple source images on one product date. Investigate rather than double-count.")
                    if key in day["pixels"]:
                        raise ValueError("Duplicate daily native pixel. Remove duplicate downloads.")
                    area = finite(row["native_pixel_area_m2"], "native_pixel_area_m2")
                    if area <= 0 or not -90 <= finite(row["pixel_center_latitude"], "pixel latitude") <= 90 or not -180 <= finite(row["pixel_center_longitude"], "pixel longitude") <= 180:
                        raise ValueError("Invalid native grid geometry.")
                    values = {}
                    for band in BANDS:
                        present = integer(row[band + "_present"], band + "_present")
                        if present not in (0, 1):
                            raise ValueError("Mask-presence flags must be 0 or 1.")
                        raw = integer(row[band], band)
                        if present == 0 and raw != config["masked_sentinel"]:
                            raise ValueError("Masked band must retain the explicit export sentinel.")
                        if present and (raw < 0 or raw > (65535 if band.startswith(("LST_", "Clear_")) else 255)):
                            raise ValueError("Unmasked band value outside its storage range.")
                        values[band] = raw if present else None
                    day["pixels"][key] = {"area": area, "values": values}
                else:
                    raise ValueError("Unknown raw row type.")
    for (location_id, year), partition in partitions.items():
        inventory = partition["inventory"]
        if inventory is None:
            raise ValueError(f"Missing partition inventory for {location_id}/{year}.")
        dates = inventory["image_dates"].split("|") if inventory["image_dates"] else []
        ids = inventory["image_ids"].split("|") if inventory["image_ids"] else []
        if len(dates) != integer(inventory["image_count"], "image_count") or len(ids) != len(dates) or len(set(dates)) != len(dates) or len(set(ids)) != len(ids):
            raise ValueError("Invalid source inventory or multiple images per date.")
        if not set(dates).issubset(dates_in_year(year)) or set(dates) != set(partition["days"]):
            raise ValueError("Truncated export or dates outside the partition.")
        keys = {tuple(map(int, key.split(":"))) for key in inventory["native_pixel_keys"].split("|") if key}
        if len(keys) != integer(inventory["native_center_count"], "native_center_count") or not keys:
            raise ValueError("Invalid native grid inventory.")
        if not inventory["grid_crs"] or not inventory["grid_transform"] or finite(inventory["requested_footprint_area_m2"], "footprint area") <= 0:
            raise ValueError("Missing projection/footprint metadata.")
        expected_images = dict(zip(dates, ids))
        for date, day in partition["days"].items():
            if day["image_id"] != expected_images[date] or set(day["pixels"]) != keys:
                raise ValueError("Truncated or inconsistent native-grid sample.")
        partition["native_center_count"] = len(keys)
    return partitions, catalog_hash


def empty_phase():
    return {"pixel_retrieval_counts": {stage: 0 for stage in STAGES},
            "distinct_product_dates": {stage: 0 for stage in STAGES},
            "calendar_date_coverage_fraction": {stage: 0.0 for stage in STAGES},
            "strict_phase_supported_calendar_date_fraction": 0.0,
            "qa_histograms": {field: {str(i): 0 for i in range(4)} for field in QA_FIELDS},
            "observation_time_raw_dn_histogram": {}, "strict_qa_observation_time_raw_dn_histogram": {},
            "relaxed_qa_observation_time_raw_dn_histogram": {}, "circular_mean_local_solar_hour": None,
            "zero_time_with_valid_lst_count": 0, "dates_with_strict_phase_support_at_threshold": 0}


def summarize_period(location, year, month, partition, config):
    expected_dates = [date for date in dates_in_year(year) if month is None or int(date[5:7]) == month]
    base = {**location, "period_type": "year" if month is None else "month",
            "period": str(year) if month is None else f"{year}-{month:02d}",
            "expected_product_dates": len(expected_dates), "input_status": "pending_export",
            "source_product_dates": None, "source_product_date_fraction": None, "missing_product_dates": None, "native_center_count": None,
            "requested_footprint_area_m2": None, "sampled_center_area_m2": None,
            "phases": None, "same_product_date_joint_strict_phase": None,
            "exploratory_screen": {"status": "not_evaluated", "reason_codes": ["pending_export"]}}
    if partition is None:
        return base
    days = {date: partition["days"][date] for date in expected_dates if date in partition["days"]}
    phases = {phase: empty_phase() for phase in ["day", "night"]}
    sums = {phase: [0.0, 0.0] for phase in phases}
    joint = {"pixel_retrieval_count": 0, "distinct_product_dates": 0,
             "dates_at_spatial_support_threshold": 0, "mean_spatial_support_fraction_over_calendar_dates": 0.0}
    support_sum = 0.0
    sampled_area = None
    threshold = config["exploratory_monthly_thresholds"]["same_product_date_spatial_support_fraction_min"]
    for day in days.values():
        date_counts = {phase: Counter() for phase in phases}
        date_areas = {phase: 0.0 for phase in phases}
        total_area = sum(pixel["area"] for pixel in day["pixels"].values())
        if sampled_area is not None and not math.isclose(sampled_area, total_area, rel_tol=1e-9):
            raise ValueError("Native sampled area changed between dates.")
        sampled_area = total_area
        joint_count, joint_area = 0, 0.0
        for pixel in day["pixels"].values():
            both = True
            for phase, prefix in [("day", "Day"), ("night", "Night")]:
                values = pixel["values"]
                time = values[prefix + "_view_time"]
                stages, qa, hour = classify_pixel(values[f"LST_{prefix}_1km"], values[f"QC_{prefix}"], time, config["phase_windows_hours"][phase])
                result = phases[phase]
                for stage, passed in stages.items():
                    result["pixel_retrieval_counts"][stage] += int(passed)
                    date_counts[phase][stage] += int(passed)
                if qa:
                    for field, value in qa.items():
                        result["qa_histograms"][field][str(value)] += 1
                if hour is not None:
                    histogram = result["observation_time_raw_dn_histogram"]
                    histogram[str(time)] = histogram.get(str(time), 0) + 1
                    for profile in ["strict", "relaxed"]:
                        if stages[profile + "_qa"]:
                            qa_histogram = result[profile + "_qa_observation_time_raw_dn_histogram"]
                            qa_histogram[str(time)] = qa_histogram.get(str(time), 0) + 1
                    sums[phase][0] += math.sin(hour * math.pi / 12)
                    sums[phase][1] += math.cos(hour * math.pi / 12)
                    result["zero_time_with_valid_lst_count"] += int(time == 0)
                if stages["strict_qa_in_phase"]:
                    date_areas[phase] += pixel["area"]
                both = both and stages["strict_qa_in_phase"]
            if both:
                joint_count += 1
                joint_area += pixel["area"]
        for phase in phases:
            for stage in STAGES:
                phases[phase]["distinct_product_dates"][stage] += int(date_counts[phase][stage] > 0)
            phases[phase]["dates_with_strict_phase_support_at_threshold"] += int(date_areas[phase] > 0 and date_areas[phase] / total_area >= threshold)
        joint["pixel_retrieval_count"] += joint_count
        joint["distinct_product_dates"] += int(joint_count > 0)
        joint["dates_at_spatial_support_threshold"] += int(joint_area > 0 and joint_area / total_area >= threshold)
        support_sum += joint_area / total_area
    for phase in phases:
        phases[phase]["calendar_date_coverage_fraction"] = {stage: phases[phase]["distinct_product_dates"][stage] / len(expected_dates) for stage in STAGES}
        phases[phase]["strict_phase_supported_calendar_date_fraction"] = phases[phase]["dates_with_strict_phase_support_at_threshold"] / len(expected_dates)
        sine, cosine = sums[phase]
        if math.hypot(sine, cosine) > 1e-12:
            hour = (math.atan2(sine, cosine) * 12 / math.pi) % 24
            phases[phase]["circular_mean_local_solar_hour"] = 0.0 if math.isclose(hour, 24, abs_tol=1e-12) else hour
    joint["mean_spatial_support_fraction_over_calendar_dates"] = support_sum / len(expected_dates)
    screen = {"status": "not_evaluated", "reason_codes": ["monthly_screen_only"]}
    if month is not None:
        thresholds = config["exploratory_monthly_thresholds"]
        reasons = []
        for phase in phases:
            count = phases[phase]["dates_with_strict_phase_support_at_threshold"]
            if count < thresholds["strict_qa_phase_dates_min"]:
                reasons.append(f"{phase}_fewer_than_provisional_minimum_dates")
            if count / len(expected_dates) < thresholds["strict_qa_phase_date_fraction_min"]:
                reasons.append(f"{phase}_below_provisional_temporal_coverage")
        if joint["dates_at_spatial_support_threshold"] / len(expected_dates) < thresholds["strict_qa_phase_date_fraction_min"]:
            reasons.append("insufficient_same_product_date_joint_support")
        screen = {"status": "below_exploratory_screen" if reasons else "meets_exploratory_screen", "reason_codes": reasons}
    base.update({"input_status": "complete", "source_product_dates": len(days), "source_product_date_fraction": len(days) / len(expected_dates),
                 "missing_product_dates": sorted(set(expected_dates) - set(days)),
                 "native_center_count": partition["native_center_count"],
                 "requested_footprint_area_m2": finite(partition["inventory"]["requested_footprint_area_m2"], "footprint area"),
                 "sampled_center_area_m2": sampled_area, "phases": phases,
                 "same_product_date_joint_strict_phase": joint, "exploratory_screen": screen})
    return base


def make_report(paths, config, config_hash, run_id):
    # Each submitted location/year is one complete CSV. Release its pixel rows
    # after summarizing, so memory scales with the largest partition, not all 30.
    period_rows = {}
    received = set()
    catalog, locations = load_locations(config)
    catalog_hash = digest(catalog)
    lookup = {location["location_id"]: location for location in locations}
    for path in paths:
        partitions, checked_hash = read_exports([path], config, config_hash, run_id)
        if checked_hash != catalog_hash:
            raise ValueError("Catalogue changed while reading exports.")
        for key, partition in partitions.items():
            if key in received:
                raise ValueError("Duplicate partition across downloaded files.")
            received.add(key)
            location_id, year = key
            for month in list(range(1, 13)) + [None]:
                period_rows[(location_id, year, month)] = summarize_period(lookup[location_id], year, month, partition, config)
    records = []
    for location in locations:
        for year in [2021, 2022, 2023]:
            for month in list(range(1, 13)) + [None]:
                key = (location["location_id"], year, month)
                records.append(period_rows[key] if key in period_rows else summarize_period(location, year, month, None, config))
    return {"schema_version": "earth-thermal-availability-report/1.0.0", "run_id": run_id,
            "dataset_id": DATASET, "catalog_sha256": catalog_hash, "config_sha256": config_hash,
            "source_product_version": "061", "export_files": [{"filename": path.name, "sha256": digest(path)} for path in paths],
            "processing_script_sha256": {name: digest(PILOT_DIR / name) for name in ["common.py", "reporting.py", "ee_export.py"]},
            "threshold_status": "provisional_diagnostic_only", "phase_windows_hours": config["phase_windows_hours"],
            "exploratory_monthly_thresholds": config["exploratory_monthly_thresholds"],
            "received_partitions": len(received), "expected_partitions": 30,
            "raw_swath_observation_count": None, "effective_independent_observation_count": None,
            "records": records}


def validate_report(report: dict, config: dict) -> None:
    """JSON Schema plus catalogue, hierarchy and monthly/yearly accounting checks."""
    import json
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        raise ValueError("Offline output validation requires jsonschema. See the environment check and approval instructions.") from None
    schema = json.loads((PILOT_DIR / "diagnostic.schema.json").read_text())
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report))
    if errors:
        raise ValueError(f"Report schema validation failed: {errors[0].message}")
    catalog, locations = load_locations(config)
    if report["catalog_sha256"] != digest(catalog) or report["phase_windows_hours"] != config["phase_windows_hours"] or report["exploratory_monthly_thresholds"] != config["exploratory_monthly_thresholds"]:
        raise ValueError("Report catalogue or diagnostic configuration mismatch.")
    lookup = {location["location_id"]: location for location in locations}
    records = {}
    for row in report["records"]:
        key = (row["location_id"], row["period"])
        if key in records or row["location_id"] not in lookup:
            raise ValueError("Duplicate or unknown report location/period.")
        records[key] = row
        if any(row[field] != value for field, value in lookup[row["location_id"]].items()):
            raise ValueError("Report changed a canonical location.")
        year = int(row["period"][:4])
        if year not in (2021, 2022, 2023):
            raise ValueError("Unexpected reporting year.")
        expected = len(dates_in_year(year)) if row["period_type"] == "year" else sum(date.startswith(row["period"]) for date in dates_in_year(year))
        if row["expected_product_dates"] != expected:
            raise ValueError("Incorrect calendar denominator.")
        if row["input_status"] == "pending_export":
            continue
        source_dates = row["source_product_dates"]
        if row["source_product_date_fraction"] != source_dates / expected:
            raise ValueError("Incorrect source-date coverage fraction.")
        if len(row["missing_product_dates"]) + source_dates != expected or len(set(row["missing_product_dates"])) != len(row["missing_product_dates"]):
            raise ValueError("Invalid missing-date accounting.")
        for phase in row["phases"].values():
            counts = phase["pixel_retrieval_counts"]
            dates = phase["distinct_product_dates"]
            for stage in STAGES:
                if phase["calendar_date_coverage_fraction"][stage] != dates[stage] / expected:
                    raise ValueError("Incorrect stage temporal coverage fraction.")
                if dates[stage] > min(source_dates, counts[stage]) or counts[stage] > row["native_center_count"] * source_dates:
                    raise ValueError("Pixel counts and distinct dates are inconsistent.")
            parents = {
                "qc_present": ["lst_valid"], "mandatory_produced": ["qc_present"],
                "mandatory_good": ["mandatory_produced"], "data_quality_good": ["qc_present"],
                "emissivity_error_le_0_01": ["qc_present"], "lst_error_le_1k": ["qc_present"],
                "time_valid": ["lst_valid"], "phase_window": ["time_valid"],
                "strict_qa": ["mandatory_good", "data_quality_good", "emissivity_error_le_0_01", "lst_error_le_1k"],
                "relaxed_qa": ["mandatory_produced"],
                "strict_qa_with_time": ["strict_qa", "time_valid", "relaxed_qa_with_time"],
                "relaxed_qa_with_time": ["relaxed_qa", "time_valid"],
                "strict_qa_in_phase": ["strict_qa_with_time", "phase_window", "relaxed_qa_in_phase"],
                "relaxed_qa_in_phase": ["relaxed_qa", "phase_window"],
            }
            for child, stages in parents.items():
                if any(counts[child] > counts[parent] or dates[child] > dates[parent] for parent in stages):
                    raise ValueError("Invalid QA/phase subset counts.")
            if any(sum(histogram.values()) != counts["qc_present"] for histogram in phase["qa_histograms"].values()):
                raise ValueError("QC histogram counts are inconsistent.")
            if sum(phase["observation_time_raw_dn_histogram"].values()) != counts["time_valid"]:
                raise ValueError("Observation-time histogram counts are inconsistent.")
            for profile in ["strict", "relaxed"]:
                if sum(phase[profile + "_qa_observation_time_raw_dn_histogram"].values()) != counts[profile + "_qa_with_time"]:
                    raise ValueError("QA-filtered time histogram is inconsistent.")
            if phase["zero_time_with_valid_lst_count"] != phase["observation_time_raw_dn_histogram"].get("0", 0):
                raise ValueError("Zero-time accounting is inconsistent.")
            if phase["strict_phase_supported_calendar_date_fraction"] != phase["dates_with_strict_phase_support_at_threshold"] / expected:
                raise ValueError("Incorrect spatially supported date fraction.")
            if phase["dates_with_strict_phase_support_at_threshold"] > dates["strict_qa_in_phase"]:
                raise ValueError("Invalid spatial-support date count.")
        joint = row["same_product_date_joint_strict_phase"]
        if joint["pixel_retrieval_count"] > min(phase["pixel_retrieval_counts"]["strict_qa_in_phase"] for phase in row["phases"].values()):
            raise ValueError("Joint support exceeds single-phase support.")
        if joint["dates_at_spatial_support_threshold"] > joint["distinct_product_dates"] or joint["distinct_product_dates"] > min(phase["distinct_product_dates"]["strict_qa_in_phase"] for phase in row["phases"].values()):
            raise ValueError("Joint date counts are inconsistent.")
    for location_id in lookup:
        for year in (2021, 2022, 2023):
            annual = records.get((location_id, str(year)))
            monthly = [records.get((location_id, f"{year}-{month:02d}")) for month in range(1, 13)]
            if annual is None or any(row is None for row in monthly):
                raise ValueError("Missing monthly/yearly record.")
            if any(row["input_status"] != annual["input_status"] for row in monthly):
                raise ValueError("Inconsistent partition status.")
            if annual["input_status"] == "complete":
                if annual["source_product_dates"] != sum(row["source_product_dates"] for row in monthly):
                    raise ValueError("Annual date count does not equal monthly totals.")
                for phase in ["day", "night"]:
                    for kind in ["pixel_retrieval_counts", "distinct_product_dates"]:
                        for stage in STAGES:
                            if annual["phases"][phase][kind][stage] != sum(row["phases"][phase][kind][stage] for row in monthly):
                                raise ValueError("Annual stage counts do not equal monthly totals.")
    complete = sum(row["input_status"] == "complete" for row in report["records"] if row["period_type"] == "year")
    if complete != report["received_partitions"]:
        raise ValueError("Partition count mismatch.")

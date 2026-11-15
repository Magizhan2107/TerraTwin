#!/usr/bin/env python3
"""Isolated availability pilot. plan/environment/report never contact Earth Engine."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys

from common import DATASET, PILOT_DIR, PILOT_LOCATIONS, digest, load_config, load_locations, within_pilot, write_json


def plan(config, config_path):
    catalog, locations = load_locations(config)
    return {
        "schema_version": "earth-thermal-availability-plan/1.0.0", "remote_executed": False,
        "dataset_id": DATASET, "catalog_sha256": digest(catalog), "config_sha256": digest(config_path),
        "configuration": config, "locations": locations,
        "partitions": [{"location_id": location["location_id"], "year": year} for location in locations for year in [2021, 2022, 2023]],
        "counting_unit": "daily Level-3 native pixel retrieval; raw swath count unknown",
        "export_mode": "one asynchronous Drive CSV per location/year",
    }


def environment():
    packages = {}
    for name in ["earthengine-api", "google-auth", "jsonschema"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": sys.version.split()[0], "interpreter": sys.executable, "packages": packages,
            "earthengine_user_credentials_file_present": (Path.home() / ".config/earthengine/credentials").is_file(),
            "google_adc_file_present": (Path.home() / ".config/gcloud/application_default_credentials.json").is_file(),
            "google_application_credentials_env_set": bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")),
            "authentication_verified": False,
            "note": "File/environment presence only. No credential contents read, login, token refresh or API calls."}


def submit(args, config, config_path):
    # This is the sole remote entry point. Never authenticates automatically.
    metadata = plan(config, config_path)
    location = next(location for location in metadata["locations"] if location["location_id"] == args.location_id)
    manifest_path = within_pilot(PILOT_DIR / "outputs/tasks" / f"{args.run_id}_{args.location_id}_{args.year}.json")
    if manifest_path.exists():
        raise ValueError(f"Submission manifest already exists: {manifest_path}. Inspect it before any retry.")
    try:
        import ee
    except ImportError:
        raise ValueError("earthengine-api is missing. Installation and authentication require separate approval. See README.") from None
    try:
        ee.Initialize(project=args.project)
    except Exception as error:
        raise ValueError(f"Earth Engine initialization failed. No automatic authentication attempted. {error}") from error
    from ee_export import COLUMNS, build_export
    description = f"tt_avail_{args.run_id}_{args.location_id}_{args.year}"
    collection = build_export(ee, config, location, args.year, args.run_id, metadata["catalog_sha256"], metadata["config_sha256"])
    task = ee.batch.Export.table.toDrive(collection=collection, description=description,
                                        folder=args.drive_folder, fileNamePrefix=description,
                                        fileFormat="CSV", selectors=COLUMNS)
    metadata.update({"run_id": args.run_id, "location_id": args.location_id, "year": args.year,
                     "project": args.project, "drive_folder": args.drive_folder, "description": description,
                     "local_python_environment": environment(), "script_sha256": {
                         name: digest(PILOT_DIR / name) for name in ["pilot.py", "common.py", "ee_export.py", "reporting.py"]},
                     "prepared_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "remote_executed": True,
                     "submission_state": "start_not_yet_confirmed", "task_id": task.id})
    # Preserve an audit trail before the mutating request. Ambiguous failures must be inspected.
    write_json(manifest_path, metadata)
    try:
        task.start()
    except Exception:
        print(f"Submission outcome uncertain. Inspect Earth Engine Tasks and {manifest_path} before retrying.", file=sys.stderr)
        raise
    metadata.update({"submission_state": "submitted", "task_id": task.id})
    temporary = manifest_path.with_suffix(".tmp")
    if temporary.exists():
        raise ValueError("Temporary task manifest exists. Inspect it before proceeding.")
    with temporary.open("x") as handle:
        json.dump(metadata, handle, indent=2, allow_nan=False)
    temporary.replace(manifest_path)
    print(json.dumps({"task_id": task.id, "description": description, "manifest": str(manifest_path)}, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PILOT_DIR / "config.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("environment", help="Offline package and credential-file presence check.")
    prepare = commands.add_parser("plan", help="Offline catalogue/partition plan. Does not import ee.")
    prepare.add_argument("--output", type=Path)
    remote = commands.add_parser("submit", help="REMOTE: submit exactly one location/year export. Run only after approval.")
    remote.add_argument("--project", required=True)
    remote.add_argument("--location-id", choices=list(PILOT_LOCATIONS), required=True)
    remote.add_argument("--year", type=int, choices=[2021, 2022, 2023], required=True)
    remote.add_argument("--run-id", required=True)
    remote.add_argument("--drive-folder", default="TerraTwinThermalAvailabilityPilot")
    local = commands.add_parser("report", help="Offline validation and summaries of downloaded CSV exports.")
    local.add_argument("--input-dir", type=Path, required=True)
    local.add_argument("--run-id", required=True)
    local.add_argument("--output", type=Path, required=True)
    local.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "environment":
            print(json.dumps(environment(), indent=2))
            return 0
        config = load_config(args.config)
        if args.command == "plan":
            value = plan(config, args.config)
            if args.output:
                write_json(args.output, value)
            else:
                print(json.dumps(value, indent=2, allow_nan=False))
        elif args.command == "submit":
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.run_id):
                raise ValueError("Run ID must be 1–40 letters, digits, hyphens or underscores.")
            submit(args, config, args.config)
        else:
            from reporting import make_report, validate_report
            paths = sorted(args.input_dir.glob("*.csv"))
            if not paths:
                raise ValueError("No downloaded CSV exports found. No availability results can be inferred.")
            value = make_report(paths, config, digest(args.config), args.run_id)
            validate_report(value, config)
            if args.require_complete and value["received_partitions"] != value["expected_partitions"]:
                raise ValueError("Not all 30 partitions were imported. Omit --require-complete for an explicitly partial report.")
            write_json(args.output, value)
            print(f"Validated report: {args.output}; partitions {value['received_partitions']}/30; thresholds remain provisional.")
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"Pilot error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

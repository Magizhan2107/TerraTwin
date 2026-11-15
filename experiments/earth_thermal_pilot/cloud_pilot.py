#!/usr/bin/env python3
"""Cloud-first pilot CLI. Only submit/status contact EE; no automatic authentication."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
from common import PILOT_DIR, PILOT_LOCATIONS, digest, load_config, load_locations, within_pilot, write_json
from cloud_aggregate import PIPELINE, VERSION, build_compact
from cloud_contract import document_from_geojson, hashes, validate


def prepare(config_path, location_id, year, run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',run_id):
        raise ValueError('Run ID must be 1–32 letters, digits, underscores or hyphens.')
    config=load_config(config_path)
    _,locations=load_locations(config)
    location=next(r for r in locations if r['location_id']==location_id)
    fingerprints,scripts=hashes(config_path,config)
    return dict(schema_version=VERSION,pipeline_version=PIPELINE,run_id=run_id,configuration=config,
                location=location,year=year,hashes=fingerprints,script_sha256=scripts,
                export_tasks=1,export_format='GeoJSON',expected_summary_records=13,
                project='landslide-1-510217',remote_executed=False,
                catalogue_partitions=[{'location_id':r['location_id'],'year':y,'status':'not_processed','observation_counts':None}
                    for r in locations for y in (2021,2022,2023)])


def initialize(project):
    if project!='landslide-1-510217':
        raise ValueError('Use the existing landslide-1-510217 project only.')
    import ee
    ee.Initialize(project=project)
    return ee


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=PILOT_DIR/'config.json')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('plan','submit'):
        p=commands.add_parser(name)
        p.add_argument('--location-id',choices=list(PILOT_LOCATIONS),required=True)
        p.add_argument('--year',type=int,choices=[2021,2022,2023],required=True)
        p.add_argument('--run-id',required=True)
        if name=='plan':p.add_argument('--output',type=Path)
        else:
            p.add_argument('--project',required=True)
            p.add_argument('--drive-folder',default='TerraTwinThermalCloudPilot')
    status=commands.add_parser('status',help='Read-only task status; never retries or edits a manifest.')
    status.add_argument('--receipt',type=Path,required=True)
    local=commands.add_parser('convert',help='Offline compact GeoJSON -> validated static JSON.')
    local.add_argument('--input',type=Path,required=True)
    local.add_argument('--manifest',type=Path,required=True)
    local.add_argument('--output',type=Path,required=True)
    check=commands.add_parser('compare',help='Offline equivalence check against existing report/raw validation CSV.')
    check.add_argument('--input',type=Path,required=True)
    check.add_argument('--baseline',type=Path,required=True)
    check.add_argument('--raw-baseline',type=Path)
    check.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command in ('plan','submit'):
            manifest=prepare(args.config,args.location_id,args.year,args.run_id)
            if args.command=='plan':
                if args.output:write_json(args.output,manifest)
                else:print(json.dumps(manifest,indent=2))
                return 0
            directory=within_pilot(PILOT_DIR/'outputs/cloud/tasks')
            prefix=f'{args.run_id}_{args.location_id}_{args.year}'
            if any(directory.glob(prefix+'*')):
                raise ValueError('Cloud run records already exist; inspect rather than retry or overwrite.')
            ee=initialize(args.project)
            collection=build_compact(ee,manifest['configuration'],manifest['location'],args.year,args.run_id,manifest['hashes'])
            import hashlib
            manifest.update(graph_sha256=hashlib.sha256(collection.serialize().encode()).hexdigest(),
                            description=f'tt_cloud_{prefix}',drive_folder=args.drive_folder,
                            prepared_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),ee_version=ee.__version__,
                            submission_state='prepared_not_started')
            # Write a new immutable intent before any mutating submission. Never reuse legacy task files.
            intent=directory/(prefix+'.prepared.json')
            write_json(intent,manifest)
            task=ee.batch.Export.table.toDrive(collection=collection,description=manifest['description'],
                    folder=args.drive_folder,fileNamePrefix=manifest['description'],fileFormat='GeoJSON')
            try:task.start()
            except Exception:
                print('Submission outcome uncertain. Inspect Earth Engine Tasks and the prepared intent; do not automatically retry.',file=sys.stderr)
                raise
            receipt={**manifest,'task_id':task.id,'submission_state':'submitted','remote_executed':True}
            path=directory/(prefix+'.submitted.json')
            write_json(path,receipt)
            print(json.dumps({'task_id':task.id,'receipt':str(path)},indent=2))
        elif args.command=='status':
            receipt=json.loads(args.receipt.read_text())
            ee=initialize(receipt['project'])
            print(json.dumps(ee.data.getTaskStatus(receipt['task_id']),indent=2))
        elif args.command=='convert':
            manifest=json.loads(args.manifest.read_text())
            config=load_config(args.config)
            current,_=hashes(args.config,config)
            # Config/catalogue must be current; pipeline is pinned to the submission's script bundle.
            if any(current[k]!=manifest['hashes'][k] for k in ('config_sha256','catalog_sha256')):
                raise ValueError('Current config/catalogue differs from submission.')
            doc=document_from_geojson(json.loads(args.input.read_text()),manifest)
            validate(doc,config,manifest['hashes'],manifest['script_sha256'])
            if any(r['run_id']!=manifest['run_id'] or r['location_id']!=manifest['location']['location_id'] or int(r['period'][:4])!=manifest['year'] for r in doc['records']):
                raise ValueError('Output does not match submitted location/year/run.')
            write_json(args.output,doc)
            print(f'Validated compact output: {args.output}')
        else:
            from cloud_compare import compare
            config=load_config(args.config)
            doc=json.loads(args.input.read_text())
            # Validate against the fingerprint claimed by the document, including script-bundle integrity.
            expected={k:doc['records'][0][k] for k in ('catalog_sha256','config_sha256','pipeline_sha256')}
            current,_=hashes(args.config,config)
            if any(expected[k]!=current[k] for k in ('catalog_sha256','config_sha256')):
                raise ValueError('Compact output has stale config/catalogue provenance.')
            validate(doc,config,expected)
            result=compare(doc,json.loads(args.baseline.read_text()),config,digest(args.config),args.raw_baseline)
            write_json(args.output,result)
            print(f"Baseline comparison: {'PASS' if result['passed'] else 'FAIL'}; {len(result['matching_fields'])} matching fields")
            return 0 if result['passed'] else 2
        return 0
    except (ValueError,OSError,KeyError,StopIteration,TypeError) as error:
        print(f'Cloud pilot error: {error}',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())

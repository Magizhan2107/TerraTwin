"""Versioned compact contract, provenance and fail-closed local validation."""
import calendar
import hashlib
import json
import math
from pathlib import Path
from common import DATASET, PILOT_DIR, digest, load_locations
from cloud_rules import METRICS, PHASES
from cloud_aggregate import VERSION, PIPELINE

FILES = ['cloud_rules.py', 'cloud_aggregate.py', 'cloud_contract.py', 'cloud_compare.py', 'cloud_pilot.py', 'common.py']
HASH_KEYS = ['catalog_sha256', 'config_sha256', 'pipeline_sha256']
IDENTITY = {
    'schema_version': {'const': VERSION}, 'pipeline_version': {'const': PIPELINE},
    'location_id': {'type': 'string'}, 'name': {'type': 'string'}, 'planet': {'const': 'Earth'},
    'canonical_latitude': {'type': 'number', 'minimum': -90, 'maximum': 90},
    'canonical_longitude': {'type': 'number', 'minimum': -180, 'maximum': 180},
    'period': {'type': 'string', 'pattern': '^202[123](-[01][0-9])?$'},
    'period_type': {'enum': ['month', 'year']}, 'run_id': {'type': 'string', 'minLength': 1},
    'dataset_id': {'const': DATASET}, 'source_product_version': {'const': '061'},
    'footprint_radius_m': {'const': 5000},
    'native_grid': {'type': 'string', 'minLength': 1}, 'grid_transform_wkt': {'type': 'string', 'minLength': 1},
    'native_centres': {'type': 'integer', 'minimum': 1},
    'sampled_centre_area_m2': {'type': 'number', 'exclusiveMinimum': 0},
    'requested_footprint_area_m2': {'type': 'number', 'exclusiveMinimum': 0},
    'threshold_status': {'const': 'provisional_diagnostic_only'}, 'mission_suitability': {'const': 'not_assessed'},
    'calendar_dates': {'type': 'integer', 'minimum': 1},
    'status_reason': {'type': 'string', 'minLength': 1},
    **{key: {'type': 'string', 'pattern': '^[a-f0-9]{64}$'} for key in HASH_KEYS},
}
COUNTS = ['source_product_dates', 'missing_product_dates', 'pixel_date_records',
          'joint_pixels', 'joint_dates', 'joint_supported_dates']
FRACTIONS = ['source_date_fraction', 'joint_mean_calendar_fraction']
for phase in PHASES:
    COUNTS.append(phase + '__supported_dates')
    FRACTIONS.append(phase + '__supported_calendar_fraction')
    for metric in METRICS:
        COUNTS.extend(f'{phase}__{metric}__{unit}' for unit in ('pixels', 'dates', 'centres'))
        FRACTIONS.append(f'{phase}__{metric}__calendar_fraction')
SUMMARY = {**{key: {'type': 'integer', 'minimum': 0} for key in COUNTS},
           **{key: {'type': 'number', 'minimum': 0, 'maximum': 1} for key in FRACTIONS},
           'source_image_ids': {'type': 'string'}, 'source_product_dates_list': {'type': 'string'},
           'coverage_screen': {'enum': ['not_evaluated_year', 'meets_exploratory_screen', 'below_exploratory_screen']},
           'unknown_qc_present': {'type': 'integer', 'enum': [0, 1]}}


def schema():
    def branch(statuses, summary):
        fields = {**IDENTITY, **(SUMMARY if summary else {}), 'status': {'enum': statuses}}
        return {'type': 'object', 'additionalProperties': False, 'properties': fields, 'required': list(fields)}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'urn:terratwin:thermal-cloud:1.0.0',
            'type': 'object', 'additionalProperties': False,
            'properties': {'schema_version': {'const': VERSION}, 'configuration': {'type': 'object'},
                           'script_sha256': {'type': 'object', 'additionalProperties': False,
                              'properties': {name: {'type': 'string', 'pattern': '^[a-f0-9]{64}$'} for name in FILES}, 'required': FILES},
                           'records': {'type': 'array', 'minItems': 13, 'maxItems': 13, 'items': {'oneOf': [
                               branch(['data_available', 'no_eligible_observations', 'insufficient_coverage'], True),
                               branch(['not_processed', 'processing_failure'], False)]}}},
            'required': ['schema_version', 'configuration', 'script_sha256', 'records']}


def hashes(config_path, config):
    catalog, _ = load_locations(config)
    scripts = {name: digest(PILOT_DIR / name) for name in FILES}
    pipeline_hash = hashlib.sha256(json.dumps(scripts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'catalog_sha256': digest(catalog), 'config_sha256': digest(config_path), 'pipeline_sha256': pipeline_hash}, scripts


def validate(document, config, expected_hashes, expected_scripts=None):
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(schema()).iter_errors(document))
    if errors:
        raise ValueError('Compact schema: ' + errors[0].message)
    if document['configuration'] != config:
        raise ValueError('Configuration differs from approved pilot configuration.')
    scripts = document['script_sha256']
    if expected_scripts is not None and scripts != expected_scripts:
        raise ValueError('Script provenance differs from submission manifest.')
    bundle = hashlib.sha256(json.dumps(scripts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if bundle != expected_hashes['pipeline_sha256']:
        raise ValueError('Pipeline fingerprint mismatch.')
    _, locations = load_locations(config)
    lookup = {r['location_id']: r for r in locations}
    records = document['records']
    if len({(r['location_id'], r['run_id'], r['period'][:4]) for r in records}) != 1:
        raise ValueError('Exactly one location/year/run per compact partition is required.')
    year = int(records[0]['period'][:4])
    if {r['period'] for r in records} != {str(year), *[f'{year}-{m:02d}' for m in range(1, 13)]}:
        raise ValueError('Exactly twelve unique months and one year required.')
    for r in records:
        for key in ('native_grid', 'grid_transform_wkt', 'native_centres', 'sampled_centre_area_m2', 'requested_footprint_area_m2'):
            if r[key] != records[0][key]:
                raise ValueError('Partition spatial metadata changed between periods.')
        if r['location_id'] not in lookup or any(r[k] != v for k, v in lookup[r['location_id']].items()):
            raise ValueError('Canonical identity/coordinates changed.')
        if any(r[k] != v for k, v in expected_hashes.items()):
            raise ValueError('Configuration/catalogue/pipeline fingerprint mismatch.')
        monthly = len(r['period']) == 7
        denominator = calendar.monthrange(year, int(r['period'][5:]))[1] if monthly else 365 + calendar.isleap(year)
        if r['period_type'] != ('month' if monthly else 'year') or r['calendar_dates'] != denominator:
            raise ValueError('Calendar period/denominator mismatch.')
        if r['status'] in ('not_processed', 'processing_failure'):
            continue  # No numeric zero observations can appear in these schema branches.
        n, c = r['source_product_dates'], r['native_centres']
        ids = r['source_image_ids'].split('|') if r['source_image_ids'] else []
        dates = r['source_product_dates_list'].split('|') if r['source_product_dates_list'] else []
        import datetime as dt
        if n > denominator or len(ids) != n or len(set(ids)) != n or len(dates) != n or len(set(dates)) != n:
            raise ValueError('Source-date/image inventory mismatch.')
        if any(not date.startswith(r['period']) or dt.date.fromisoformat(date).year != year for date in dates):
            raise ValueError('Source date outside period.')
        if r['pixel_date_records'] != n*c or r['missing_product_dates'] != denominator-n:
            raise ValueError('Pixel/date accounting mismatch.')
        if not math.isclose(r['source_date_fraction'], n/denominator, abs_tol=1e-12):
            raise ValueError('Source-date coverage denominator mismatch.')
        for p in PHASES:
            get = lambda m, unit: r[f'{p}__{m}__{unit}']
            for m in METRICS:
                pix, dates_n, cells = [get(m, unit) for unit in ('pixels', 'dates', 'centres')]
                if pix > n*c or dates_n > min(n,pix) or cells > min(c,pix) or bool(pix) != bool(dates_n) or bool(pix) != bool(cells):
                    raise ValueError('Pixel/date/centre count inconsistency.')
                if not math.isclose(get(m, 'calendar_fraction'), dates_n/denominator, abs_tol=1e-12):
                    raise ValueError('Stage coverage denominator mismatch.')
            for unit in ('pixels', 'dates', 'centres'):
                for m in METRICS:
                    parent = None if m in ('lst_band_present', 'qc_band_present', 'time_band_present') else 'lst_valid'
                    if parent and get(m,unit) > get(parent,unit):
                        raise ValueError('Stage exceeds valid LST population.')
                for child, parent in [('lst_valid','lst_band_present'), ('qc_present','qc_band_present'),
                                      ('strict_qa','relaxed_qa'), ('strict_qa','mandatory_good'),
                                      ('strict_qa','data_quality_good'), ('strict_qa','emissivity_error_le_0_01'),
                                      ('strict_qa','lst_error_le_1k'), ('relaxed_qa','qc_present'),
                                      ('strict_qa_with_time','strict_qa'), ('strict_qa_with_time','time_valid'),
                                      ('relaxed_qa_with_time','relaxed_qa'), ('relaxed_qa_with_time','time_valid'),
                                      ('strict_qa_in_phase','strict_qa_with_time'), ('strict_qa_in_phase','phase_window'),
                                      ('relaxed_qa_in_phase','relaxed_qa_with_time'), ('relaxed_qa_in_phase','phase_window'),
                                      ('phase_window','time_valid'), ('time_valid','time_band_present')]:
                    if get(child,unit) > get(parent,unit):
                        raise ValueError('QA/time subset violation.')
                if get('qc_valid',unit) != get('qc_present',unit) or get('time_interpretable',unit) != get('time_valid',unit):
                    raise ValueError('Metric alias mismatch.')
            if get('qc_present','pixels') + get('qc_missing','pixels') != get('lst_valid','pixels'):
                raise ValueError('Missing/known QC accounting mismatch.')
            supported = r[p+'__supported_dates']
            if supported > get('strict_qa_in_phase','dates') or not math.isclose(r[p+'__supported_calendar_fraction'], supported/denominator, abs_tol=1e-12):
                raise ValueError('Spatial support count/fraction mismatch.')
        if r['unknown_qc_present'] != int(any(r[p+'__qc_missing__pixels'] > 0 for p in PHASES)):
            raise ValueError('Unknown QC indicator mismatch.')
        if r['joint_pixels'] > min(r[p+'__strict_qa_in_phase__pixels'] for p in PHASES) or r['joint_dates'] > min(r[p+'__strict_qa_in_phase__dates'] for p in PHASES) or r['joint_supported_dates'] > r['joint_dates']:
            raise ValueError('Joint support exceeds phase support.')
        limits = config['exploratory_monthly_thresholds']
        enough = all(r[p+'__supported_dates'] >= limits['strict_qa_phase_dates_min'] and r[p+'__supported_calendar_fraction'] >= limits['strict_qa_phase_date_fraction_min'] for p in PHASES) and r['joint_supported_dates']/denominator >= limits['strict_qa_phase_date_fraction_min']
        nonzero = all(r[p+'__strict_qa_in_phase__dates'] > 0 for p in PHASES)
        expected_status = 'no_eligible_observations' if not nonzero else 'insufficient_coverage' if monthly and not enough else 'data_available'
        expected_screen = 'not_evaluated_year' if not monthly else 'meets_exploratory_screen' if enough else 'below_exploratory_screen'
        if r['status'] != expected_status or r['coverage_screen'] != expected_screen:
            raise ValueError('Status does not match unchanged provisional screen.')
    annual = next(r for r in records if r['period_type'] == 'year')
    months = [r for r in records if r['period_type'] == 'month']
    done = lambda r: r['status'] not in ('not_processed','processing_failure')
    if all(done(r) for r in records):
        for key in COUNTS:
            if not key.endswith('__centres') and key not in ('missing_product_dates',) and annual[key] != sum(m[key] for m in months):
                raise ValueError('Annual/monthly count mismatch: '+key)
        for p in PHASES:
            for m in METRICS:
                key=f'{p}__{m}__centres'
                if not max(r[key] for r in months) <= annual[key] <= min(annual['native_centres'], sum(r[key] for r in months)):
                    raise ValueError('Yearly contributing-centre union bounds violated.')
        if set(filter(None,annual['source_product_dates_list'].split('|'))) != set(date for m in months for date in m['source_product_dates_list'].split('|') if date):
            raise ValueError('Annual/monthly source inventory mismatch.')


def document_from_geojson(data, manifest):
    if data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
        raise ValueError('Expected compact GeoJSON FeatureCollection.')
    records = []
    for feature in data['features']:
        geometry = feature.get('geometry')
        # EE represents null summary geometry as an empty MultiPoint on export.
        empty_geometry = geometry is None or geometry == {'type': 'MultiPoint', 'coordinates': []}
        if feature.get('type') != 'Feature' or not empty_geometry or not isinstance(feature.get('properties'), dict):
            raise ValueError('Expected non-geographic period summary features.')
        props = dict(feature['properties'])
        # EE may add this transport field; all other unexpected fields fail schema validation.
        props.pop('system:index', None)
        records.append(props)
    return {'schema_version': VERSION, 'configuration': manifest['configuration'],
            'script_sha256': manifest['script_sha256'], 'records': records}

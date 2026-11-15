"""Offline comparator only. Raw rows are a validation oracle, never cloud outputs."""
from collections import Counter
from common import BANDS, STAGES, classify_pixel, digest
from reporting import read_exports
from cloud_rules import EXTRA, METRICS, PHASES
from cloud_contract import IDENTITY, SUMMARY


def compare(document, baseline, config, config_hash, raw_path=None):
    import math
    rows = document['records']
    result = {'matching_fields': [], 'mismatched_fields': [], 'missing_fields': [],
              'unexpected_fields': [], 'unverified_fields': [], 'baseline_discrepancies': [],
              'definition_notes': [
                  'qc_present/qc_valid require valid LST; qc_band_present counts source-mask presence on all sampled rows.',
                  'qc_missing counts valid LST with absent QC; masked bytes never become QA=0.',
                  'centres are period unions, dates are distinct UTC product dates; neither denotes statistical independence.',
                  'New mask metrics and contributing-centre counts require the existing raw validation CSV; the legacy report lacks them.',
                  'Run/pipeline identifiers differ by design; configuration/catalogue hashes and coordinates must match.']}
    def check(label, actual, expected):
        if isinstance(actual, (int,float)) and isinstance(expected, (int,float)):
            equal = math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
        else:
            equal = actual == expected
        if equal:
            result['matching_fields'].append(label)
        else:
            result['mismatched_fields'].append({'field': label, 'cloud': actual, 'baseline': expected,
                'possible_cause': 'Review source revisions, native-centre inclusion/grid, time predicates, source inventory and provenance; do not tune thresholds.'})
    partitions = {}
    if raw_path is not None:
        partitions, _ = read_exports([raw_path], config, config_hash, baseline['run_id'])
        if baseline['export_files'] != [{'filename': raw_path.name, 'sha256': digest(raw_path)}]:
            raise ValueError('Raw validation file does not match baseline report fingerprint.')
    expected_keys = set(IDENTITY) | set(SUMMARY) | {'status'}
    seen = set()
    for row in rows:
        prefix = str(row.get('location_id'))+'/'+str(row.get('period'))
        key = (row.get('location_id'), row.get('period'))
        if key in seen:
            result['unexpected_fields'].append(prefix+'/duplicate_record')
        seen.add(key)
        result['missing_fields'].extend(prefix+'/'+k for k in sorted(expected_keys-set(row)))
        result['unexpected_fields'].extend(prefix+'/'+k for k in sorted(set(row)-expected_keys))
        ref = next((r for r in baseline['records'] if (r['location_id'],r['period']) == key and r['input_status']=='complete'), None)
        if ref is None:
            result['missing_fields'].append(prefix+'/processed_offline_baseline')
            continue
        expected = {k: ref[k] for k in ['location_id','name','canonical_latitude','canonical_longitude','period','period_type']}
        expected.update(catalog_sha256=baseline['catalog_sha256'], config_sha256=baseline['config_sha256'],
                        source_product_dates=ref['source_product_dates'], calendar_dates=ref['expected_product_dates'],
                        source_date_fraction=ref['source_product_date_fraction'], missing_product_dates=len(ref['missing_product_dates']),
                        native_centres=ref['native_center_count'], pixel_date_records=ref['native_center_count']*ref['source_product_dates'],
                        sampled_centre_area_m2=ref['sampled_center_area_m2'], requested_footprint_area_m2=ref['requested_footprint_area_m2'])
        for p in PHASES:
            phase = ref['phases'][p]
            for m in STAGES:
                expected[f'{p}__{m}__pixels'] = phase['pixel_retrieval_counts'][m]
                expected[f'{p}__{m}__dates'] = phase['distinct_product_dates'][m]
                expected[f'{p}__{m}__calendar_fraction'] = phase['calendar_date_coverage_fraction'][m]
            expected[p+'__supported_dates'] = phase['dates_with_strict_phase_support_at_threshold']
            expected[p+'__supported_calendar_fraction'] = phase['strict_phase_supported_calendar_date_fraction']
        joint=ref['same_product_date_joint_strict_phase']
        expected.update(joint_pixels=joint['pixel_retrieval_count'], joint_dates=joint['distinct_product_dates'],
                        joint_supported_dates=joint['dates_at_spatial_support_threshold'],
                        joint_mean_calendar_fraction=joint['mean_spatial_support_fraction_over_calendar_dates'])
        partition=partitions.get((key[0], int(key[1][:4])))
        if partition is not None:
            expected.update(native_grid=partition['inventory']['grid_crs'], grid_transform_wkt=partition['inventory']['grid_transform'])
            dates=sorted(d for d in partition['days'] if d.startswith(key[1]))
            expected['source_product_dates_list']='|'.join(dates)
            expected['source_image_ids']='|'.join(partition['days'][d]['image_id'] for d in dates)
            for p in PHASES:
                counts=Counter(); date_sets={m:set() for m in METRICS}; centres={m:set() for m in METRICS}
                prefix_band=p.title()
                for date in dates:
                    for cell, pixel in partition['days'][date]['pixels'].items():
                        v=pixel['values'];lst=v[f'LST_{prefix_band}_1km'];qc=v[f'QC_{prefix_band}'];time=v[prefix_band+'_view_time']
                        stages,_,_=classify_pixel(lst,qc,time,config['phase_windows_hours'][p])
                        metrics={**stages,'lst_band_present':lst is not None,'qc_band_present':qc is not None,
                                 'time_band_present':time is not None,'qc_missing':stages['lst_valid'] and qc is None,
                                 'qc_valid':stages['qc_present'],'time_missing':stages['lst_valid'] and time is None,
                                 'time_interpretable':stages['time_valid']}
                        for m, passed in metrics.items():
                            if passed:
                                counts[m]+=1;date_sets[m].add(date);centres[m].add(cell)
                for m in METRICS:
                    expected[f'{p}__{m}__centres']=len(centres[m])
                    if m in EXTRA:
                        expected[f'{p}__{m}__pixels']=counts[m]
                        expected[f'{p}__{m}__dates']=len(date_sets[m])
                        expected[f'{p}__{m}__calendar_fraction']=len(date_sets[m])/ref['expected_product_dates']
                    elif counts[m] != expected[f'{p}__{m}__pixels'] or len(date_sets[m]) != expected[f'{p}__{m}__dates']:
                        result['baseline_discrepancies'].append(prefix+'/'+p+'/'+m)
            expected['unknown_qc_present']=int(any(expected[p+'__qc_missing__pixels'] for p in PHASES))
        else:
            result['unverified_fields'].append(prefix+'/raw_mask_availability_and_contributing_centres')
        for k,v in expected.items():
            if k in row:
                # Explicit source-empty periods may have no sampled area in the legacy reporter.
                if v is None:
                    if k == 'sampled_centre_area_m2' and ref['source_product_dates'] == 0 and partition is not None:
                        # Legacy report leaves area null on empty periods. The invariant
                        # grid area is checked against populated periods by the validator.
                        result['definition_notes'].append(prefix+'/sampled area: legacy empty-period null; compact retains invariant grid area.')
                    else:
                        result['unverified_fields'].append(prefix+'/'+k)
                else:
                    check(prefix+'/'+k,row[k],v)
    complete={r['period'] for r in baseline['records'] if rows and r['location_id']==rows[0].get('location_id') and r['period'][:4]==rows[0].get('period','')[:4] and r['input_status']=='complete'}
    result['missing_fields'].extend('period/'+p for p in sorted(complete-{r.get('period') for r in rows}))
    result['passed']=not any(result[k] for k in ['mismatched_fields','missing_fields','unexpected_fields','unverified_fields','baseline_discrepancies'])
    return result

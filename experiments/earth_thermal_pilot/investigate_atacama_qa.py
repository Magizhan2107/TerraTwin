"""Independent, offline Atacama QA audit. Does not import EE or pilot classifiers.

Reads the existing CSV/report; exclusively creates fresh investigation outputs.
Run with the pilot Python environment and -B. No thresholds are changed.
"""
from collections import Counter
import calendar
import csv
import hashlib
import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW = BASE / 'outputs/downloads/tt_avail_availability_pilot_002_24_2021.csv'
REPORT = BASE / 'outputs/availability_pilot_002.json'
OUT = BASE / 'outputs/atacama_2021_nighttime_qa_investigation.json'
FIELDS = ('mandatory', 'data_quality', 'emissivity_error', 'lst_error')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observation(row, phase):
    prefix = phase.title()
    names = (f'LST_{prefix}_1km', f'QC_{prefix}', f'{prefix}_view_time')
    values = []
    present = []
    for name in names:
        flag = int(row[name + '_present'])
        assert flag in (0, 1)
        raw = int(row[name])
        assert flag or raw == -9999
        values.append(raw if flag else None)
        present.append(bool(flag))
    lst, qc, time = values
    valid = lst is not None and 7500 <= lst <= 65535
    qc_valid = qc is not None and 0 <= qc <= 255
    qa = tuple((qc >> shift) & 3 for shift in (0, 2, 4, 6)) if qc_valid else None
    time_valid = time is not None and 0 <= time <= 240
    hour = (time * 0.1) % 24 if time_valid else None
    start, end = (13, 15) if phase == 'day' else (1, 3)
    in_phase = time_valid and start <= hour < end
    q = valid and qc_valid
    strict = q and qa == (0, 0, 0, 0)
    relaxed = q and qa[0] <= 1 and qa[1] == 0 and qa[2] <= 1 and qa[3] <= 1
    stages = dict(
        lst_valid=valid, qc_present=q,
        mandatory_produced=q and qa[0] <= 1,
        mandatory_good=q and qa[0] == 0,
        data_quality_good=q and qa[1] == 0,
        emissivity_error_le_0_01=q and qa[2] == 0,
        lst_error_le_1k=q and qa[3] == 0,
        time_valid=valid and time_valid, phase_window=valid and in_phase,
        strict_qa=strict, relaxed_qa=relaxed,
        strict_qa_with_time=strict and time_valid,
        relaxed_qa_with_time=relaxed and time_valid,
        strict_qa_in_phase=strict and in_phase,
        relaxed_qa_in_phase=relaxed and in_phase)
    return dict(lst=lst, qc=qc, time=time, present=present, qa=qa,
                qc_valid=qc_valid, time_valid=time_valid, hour=hour,
                in_phase=in_phase, stages=stages)


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(map(str, headers)) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def summarize(rows, phase, denominator):
    obs = [(r, observation(r, phase)) for r in rows]
    stages = next(iter(obs))[1]['stages']
    summary = {}
    for stage in stages:
        selected = [(r, o) for r, o in obs if o['stages'][stage]]
        dates = {r['product_date_utc'] for r, _ in selected}
        centres = {(r['pixel_x'], r['pixel_y']) for r, _ in selected}
        summary[stage] = dict(pixel_dates=len(selected), distinct_product_dates=len(dates),
                              distinct_centres=len(centres), calendar_date_fraction=len(dates) / denominator)
    valid = [o for _, o in obs if o['stages']['lst_valid']]
    qc = [o for o in valid if o['qc_valid']]
    hist = {field: {str(i): sum(o['qa'][j] == i for o in qc) for i in range(4)}
            for j, field in enumerate(FIELDS)}
    times = {}
    for name, predicate in [('all', lambda o: o['stages']['time_valid']),
                            ('strict', lambda o: o['stages']['strict_qa_with_time']),
                            ('relaxed', lambda o: o['stages']['relaxed_qa_with_time'])]:
        times[name] = dict(sorted(Counter(str(o['time']) for o in valid if predicate(o)).items(), key=lambda x: int(x[0])))
    mask = Counter(('LST_valid' if o['stages']['lst_valid'] else 'LST_invalid') +
                   ('/QC_present' if o['present'][1] else '/QC_masked') for _, o in obs)
    raw_codes = []
    for code in sorted({o['qc'] for _, o in obs if o['qc_valid']}):
        decoded = tuple((code >> shift) & 3 for shift in (0, 2, 4, 6))
        raw_codes.append(dict(raw=code, all_pixel_dates=sum(o['qc'] == code for _, o in obs),
                              valid_lst_pixel_dates=sum(o['qc'] == code for o in valid),
                              decoded=dict(zip(FIELDS, decoded)), strict=decoded == (0, 0, 0, 0),
                              relaxed=decoded[0] <= 1 and decoded[1] == 0 and decoded[2] <= 1 and decoded[3] <= 1))
    predicates = [
        ('total', lambda o: True, len(obs)),
        ('lst_band_present', lambda o: o['present'][0], len(obs)),
        ('lst_valid', lambda o: o['stages']['lst_valid'], sum(o['present'][0] for _, o in obs)),
        ('qc_band_present', lambda o: o['present'][1], len(valid)),
        ('qc_interpretable', lambda o: o['qc_valid'], sum(o['present'][1] for o in valid)),
        ('mandatory_good', lambda o: o['qc_valid'] and o['qa'][0] == 0, len(qc)),
        ('data_quality_good', lambda o: o['qc_valid'] and o['qa'][1] == 0, len(qc)),
        ('emissivity_error_le_0_01', lambda o: o['qc_valid'] and o['qa'][2] == 0, len(qc)),
        ('lst_error_le_1k', lambda o: o['qc_valid'] and o['qa'][3] == 0, len(qc)),
        ('strict_qa', lambda o: o['stages']['strict_qa'], len(qc)),
        ('time_band_present', lambda o: o['present'][2], len(valid)),
        ('time_valid', lambda o: o['time_valid'], sum(o['present'][2] for o in valid)),
        ('phase_window', lambda o: o['in_phase'], sum(o['time_valid'] for o in valid)),
        ('strict_qa_in_phase', lambda o: o['stages']['strict_qa_in_phase'], len(qc))]
    waterfall = []
    survivors = [o for _, o in obs]
    for name, predicate, independent_denominator in predicates:
        # Independent QA/time criteria use valid LST; QA-bit criteria additionally require QC.
        base = [o for _, o in obs] if name in ('total', 'lst_band_present', 'lst_valid') else valid
        independent = sum(predicate(o) for o in base)
        previous = len(survivors)
        survivors = [o for o in survivors if predicate(o)]
        waterfall.append(dict(criterion=name, independent_pass=independent,
                              independent_denominator=independent_denominator,
                              cumulative_pass=len(survivors), cumulative_input=previous))
    # Relaxed is a parallel profile, never appended after the strict zero.
    relaxed_chain = []
    survivors = list(qc)
    for name, predicate in [('mandatory_le_1', lambda o: o['qa'][0] <= 1),
                            ('data_quality_0', lambda o: o['qa'][1] == 0),
                            ('emissivity_le_1', lambda o: o['qa'][2] <= 1),
                            ('lst_error_le_1', lambda o: o['qa'][3] <= 1),
                            ('time_present', lambda o: o['present'][2]),
                            ('time_valid', lambda o: o['time_valid']),
                            ('phase_window', lambda o: o['in_phase'])]:
        before = len(survivors)
        survivors = [o for o in survivors if predicate(o)]
        relaxed_chain.append(dict(criterion=name, independent_pass=sum(predicate(o) for o in qc),
                                  independent_denominator=len(qc), cumulative_input=before,
                                  cumulative_pass=len(survivors)))
    time_values = [o['hour'] for o in valid if o['time_valid']]
    sine = sum(math.sin(hour * math.pi / 12) for hour in time_values)
    cosine = sum(math.cos(hour * math.pi / 12) for hour in time_values)
    circular = (math.atan2(sine, cosine) * 12 / math.pi) % 24 if math.hypot(sine, cosine) > 1e-12 else None
    return dict(stages=summary, qa_fields_valid_lst_and_qc=hist, raw_qc_codes=raw_codes,
                raw_qc_masked=sum(not o['present'][1] for _, o in obs),
                mask_cross_tab=dict(mask), time_dn_histograms=times,
                zero_time_with_valid_lst_count=sum(o['time'] == 0 for o in valid),
                circular_mean_local_solar_hour=circular,
                strict_waterfall=waterfall, relaxed_waterfall=relaxed_chain,
                time_range_hours=[min(time_values), max(time_values)] if time_values else None,
                missing_qc_valid_lst_in_window=sum(not o['present'][1] and o['in_phase'] for o in valid),
                lst_kelvin_range=[min(o['lst'] for o in valid)*0.02, max(o['lst'] for o in valid)*0.02])


def main():
    if OUT.exists():
        raise ValueError('Investigation output exists; refusing overwrite.')
    before = {str(p.relative_to(BASE)): sha(p) for p in BASE.rglob('*')
              if p.is_file() and not {'.venv', '__pycache__'}.intersection(p.parts)}
    config = json.loads((BASE / 'config.json').read_text())
    assert config['phase_windows_hours'] == {'day': [13, 15], 'night': [1, 3]}
    assert config['footprint_radius_m'] == 5000
    with RAW.open(newline='') as handle:
        all_rows = list(csv.DictReader(handle))
    inventory, = [r for r in all_rows if r['record_type'] == 'partition_inventory']
    rows = [r for r in all_rows if r['record_type'] == 'pixel']
    assert len(rows) == 32850 and len({r['product_date_utc'] for r in rows}) == 365
    assert all(r['location_id'] == '24' and r['year'] == '2021' for r in rows)
    assert len({(r['pixel_x'], r['pixel_y']) for r in rows}) == 90
    original = json.loads(REPORT.read_text())
    periods, checks, differences = {}, 0, []
    def compare(path, actual, expected):
        nonlocal checks
        checks += 1
        equal = math.isclose(actual, expected, abs_tol=1e-10, rel_tol=1e-10) if isinstance(actual, float) and isinstance(expected, (float, int)) else actual == expected
        if not equal:
            differences.append(dict(metric=path, independent=actual, report=expected))
    for month in [None] + list(range(1, 13)):
        period = '2021' if month is None else f'2021-{month:02d}'
        selected = rows if month is None else [r for r in rows if r['product_date_utc'].startswith(period)]
        days = 365 if month is None else calendar.monthrange(2021, month)[1]
        phases = {phase: summarize(selected, phase, days) for phase in ('day', 'night')}
        ref = next(r for r in original['records'] if r['location_id'] == '24' and r['period'] == period)
        compare(period + '/source_product_dates', len({r['product_date_utc'] for r in selected}), ref['source_product_dates'])
        dates = sorted({r['product_date_utc'] for r in selected})
        supported = {phase: 0 for phase in phases}
        joint_count = joint_dates = joint_supported = 0
        joint_fraction_sum = 0.0
        for date in dates:
            daily = [r for r in selected if r['product_date_utc'] == date]
            total_area = sum(float(r['native_pixel_area_m2']) for r in daily)
            assert len(daily) == 90
            area = {phase: 0.0 for phase in phases}
            joint_area, n_joint = 0.0, 0
            for row in daily:
                hits = {phase: observation(row, phase)['stages']['strict_qa_in_phase'] for phase in phases}
                for phase in phases:
                    if hits[phase]:
                        area[phase] += float(row['native_pixel_area_m2'])
                if all(hits.values()):
                    joint_area += float(row['native_pixel_area_m2'])
                    n_joint += 1
            threshold = config['exploratory_monthly_thresholds']['same_product_date_spatial_support_fraction_min']
            for phase in phases:
                supported[phase] += int(area[phase] > 0 and area[phase] / total_area >= threshold)
            joint_count += n_joint
            joint_dates += n_joint > 0
            joint_supported += joint_area > 0 and joint_area / total_area >= threshold
            joint_fraction_sum += joint_area / total_area
        for phase, data in phases.items():
            rphase = ref['phases'][phase]
            for stage, counts in data['stages'].items():
                for independent, reported in [('pixel_dates', 'pixel_retrieval_counts'), ('distinct_product_dates', 'distinct_product_dates'), ('calendar_date_fraction', 'calendar_date_coverage_fraction')]:
                    compare(f'{period}/{phase}/{reported}/{stage}', counts[independent], rphase[reported][stage])
            compare(f'{period}/{phase}/qa_histograms', data['qa_fields_valid_lst_and_qc'], rphase['qa_histograms'])
            for profile, field in [('all', 'observation_time_raw_dn_histogram'), ('strict', 'strict_qa_observation_time_raw_dn_histogram'), ('relaxed', 'relaxed_qa_observation_time_raw_dn_histogram')]:
                compare(f'{period}/{phase}/{field}', data['time_dn_histograms'][profile], rphase[field])
            for field in ('circular_mean_local_solar_hour', 'zero_time_with_valid_lst_count'):
                compare(f'{period}/{phase}/{field}', data[field], rphase[field])
            compare(f'{period}/{phase}/supported_dates', supported[phase], rphase['dates_with_strict_phase_support_at_threshold'])
            compare(f'{period}/{phase}/supported_fraction', supported[phase]/days, rphase['strict_phase_supported_calendar_date_fraction'])
        joint = dict(pixel_retrieval_count=joint_count, distinct_product_dates=joint_dates,
                     dates_at_spatial_support_threshold=joint_supported,
                     mean_spatial_support_fraction_over_calendar_dates=joint_fraction_sum/days)
        compare(period + '/joint_support', joint, ref['same_product_date_joint_strict_phase'])
        periods[period] = dict(calendar_dates=days, source_product_dates=len(dates),
                               pixel_date_rows=len(selected), phases=phases,
                               strict_phase_spatially_supported_dates=supported, joint_strict_phase=joint)
    for phase in ('day', 'night'):
        for stage in periods['2021']['phases'][phase]['stages']:
            for kind in ('pixel_dates', 'distinct_product_dates'):
                assert periods['2021']['phases'][phase]['stages'][stage][kind] == sum(periods[f'2021-{m:02d}']['phases'][phase]['stages'][stage][kind] for m in range(1, 13))
    assert not differences, differences
    assert all(sha(BASE / path) == checksum for path, checksum in before.items())
    result = dict(investigation_version='offline-atacama-qa/1.0.0',
                  source_csv_sha256=sha(RAW), source_report_sha256=sha(REPORT),
                  processing='independent standard-library reconstruction; no pilot classifier imports or network',
                  report_comparison_checks=checks, report_discrepancies=differences,
                  existing_files_sha256=before, all_existing_files_unchanged=True,
                  periods=periods)
    with OUT.open('x') as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(f'{OUT}: {checks} comparisons; {len(differences)} differences; inputs unchanged')


if __name__ == '__main__':
    main()

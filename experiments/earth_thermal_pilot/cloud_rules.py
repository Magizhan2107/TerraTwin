"""Compile existing scalar scientific rules into EE lookup tables, without EE I/O.

This keeps common.py authoritative: no second set of QA cutoffs/time windows.
The uint16/uint8 domains describe product storage, not new scientific cutoffs.
"""
from functools import lru_cache
from common import STAGES, classify_pixel, decode_time, in_window

EXTRA = ['lst_band_present', 'qc_band_present', 'time_band_present',
         'qc_missing', 'qc_valid', 'time_missing', 'time_interpretable']
METRICS = list(STAGES) + EXTRA
PHASES = ('day', 'night')


@lru_cache(maxsize=1)
def lst_domain():
    valid = [n for n in range(2**16) if classify_pixel(n, None, None, [0, 1])[0]['lst_valid']]
    if not valid or valid != list(range(valid[0], valid[-1] + 1)):
        raise ValueError('LST validity is no longer a contiguous storage-domain interval; review cloud adapter.')
    return valid[0], valid[-1]


def lookup_rules(window):
    representative_lst = lst_domain()[0]
    qa = {stage: [int(classify_pixel(representative_lst, n, None, window)[0][stage])
                  for n in range(2**8)]
          for stage in ['mandatory_produced', 'mandatory_good', 'data_quality_good',
                        'emissivity_error_le_0_01', 'lst_error_le_1k', 'strict_qa', 'relaxed_qa', 'qc_present']}
    return qa, [int(decode_time(n) is not None) for n in range(2**8)], [
        int(in_window(decode_time(n), window)) for n in range(2**8)]


def flags(ee, image, phase, config):
    """Fully unmasked 0/1 diagnostics; missing QC payload stays sentinel, not QA=0."""
    prefix = phase.title()
    bands = [f'LST_{prefix}_1km', f'QC_{prefix}', f'{prefix}_view_time']
    raw = image.select(bands)
    present = raw.mask().unmask(0, sameFootprint=False).gt(0)
    values = raw.toInt32().unmask(config['masked_sentinel'], sameFootprint=False)
    lst, qc, time = [values.select(b) for b in bands]
    lp, qp, tp = [present.select(b) for b in bands]
    lo, hi = lst_domain()
    valid = lp.And(lst.gte(lo)).And(lst.lte(hi))
    qa_rules, valid_times, in_phase_times = lookup_rules(config['phase_windows_hours'][phase])
    domain = list(range(2**8))
    qa = {key: valid.And(qp).And(qc.remap(domain, table, 0)) for key, table in qa_rules.items()}
    time_valid = valid.And(tp).And(time.remap(domain, valid_times, 0))
    phase_valid = valid.And(tp).And(time.remap(domain, in_phase_times, 0))
    result = {**qa, 'lst_valid': valid, 'time_valid': time_valid, 'phase_window': phase_valid,
              'lst_band_present': lp, 'qc_band_present': qp, 'time_band_present': tp,
              'qc_missing': valid.And(qp.Not()), 'qc_valid': qa['qc_present'],
              'time_missing': valid.And(tp.Not()), 'time_interpretable': time_valid}
    for profile in ('strict', 'relaxed'):
        result[profile + '_qa_with_time'] = qa[profile + '_qa'].And(time_valid)
        result[profile + '_qa_in_phase'] = qa[profile + '_qa'].And(phase_valid)
    return result

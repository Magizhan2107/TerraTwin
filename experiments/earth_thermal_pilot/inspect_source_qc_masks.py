"""Authorized bounded source-mask audit: six centres, one computeValue request.

Never exports, starts tasks, authenticates interactively, or changes pilot data.
Uses existing Earth Engine credentials. Refuses to overwrite its evidence file.
"""
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent
RAW = BASE / 'outputs/downloads/tt_avail_availability_pilot_002_24_2021.csv'
OUT = BASE / 'outputs/atacama_2021_source_qc_mask_provenance.json'
DATASET = 'MODIS/061/MYD11A1'
BANDS = ['LST_Day_1km', 'LST_Night_1km', 'QC_Day', 'QC_Night',
         'Day_view_time', 'Night_view_time']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists():
        raise ValueError('Evidence already exists; refusing overwrite or remote rerun.')
    before = {str(p.relative_to(BASE)): sha(p) for p in BASE.rglob('*')
              if p.is_file() and not {'.venv', '__pycache__'}.intersection(p.parts)}
    with RAW.open(newline='') as handle:
        records = list(csv.DictReader(handle))
    inventory, = [r for r in records if r['record_type'] == 'partition_inventory']
    rows = [r for r in records if r['record_type'] == 'pixel']
    selected = []
    pools = {}
    for category in ['masked', '65', '129']:
        pool = [r for r in rows if r['LST_Night_1km_present'] == '1'
                and 7500 <= int(r['LST_Night_1km']) <= 65535
                and r['LST_Day_1km_present'] == '1'
                and 7500 <= int(r['LST_Day_1km']) <= 65535
                and r['QC_Day_present'] == '1'
                and ((category == 'masked' and r['QC_Night_present'] == '0')
                     or (category != 'masked' and r['QC_Night_present'] == '1'
                         and r['QC_Night'] == category))]
        pool.sort(key=lambda r: (r['product_date_utc'], float(r['pixel_x']), float(r['pixel_y']), r['image_id']))
        assert len(pool) >= 2
        pools[category] = dict(pixel_dates=len(pool), product_dates=len({r['product_date_utc'] for r in pool}))
        selected.extend([(category, pool[0]), (category, pool[-1])])
    assert len({(r['image_id'], r['pixel_x'], r['pixel_y']) for _, r in selected}) == 6

    import ee
    # Explicitly prevent any accidental asynchronous task submission.
    with patch.object(ee.batch.Task, 'start', side_effect=AssertionError('Task starts forbidden')):
        ee.Initialize(project='landslide-1-510217')
        ee.data.setDeadline(60000)
        reference = ee.Image(DATASET + '/2021_01_01').select('LST_Day_1km').projection()
        def describe(projection):
            return ee.Dictionary(dict(crs=projection.crs(), transform_wkt=projection.transform(),
                                      nominal_scale_m=projection.nominalScale()))
        entries = []
        for category, row in selected:
            image = ee.Image(DATASET + '/' + row['image_id'])
            raw = image.select(BANDS)
            # Do not unmask source values: absent properties remain null/absent.
            masks = raw.mask().unmask(0, sameFootprint=False).rename([b + '_source_mask' for b in BANDS])
            probe = raw.addBands(masks).addBands(
                ee.Image.pixelCoordinates(reference).rename(['pixel_x', 'pixel_y'])
            ).addBands(ee.Image.pixelLonLat().rename(['pixel_center_longitude', 'pixel_center_latitude']))
            region = ee.Geometry.Point([float(row['pixel_center_longitude']),
                                       float(row['pixel_center_latitude'])]).buffer(10, 0.1)
            sample = probe.sample(region=region, projection=reference,
                                  dropNulls=False, geometries=False, tileScale=4)
            entries.append(ee.Dictionary(dict(category=category, image_id=image.id(),
                           product_date_utc=image.date().format('YYYY-MM-dd'),
                           band_projections=ee.Dictionary({b: describe(image.select(b).projection()) for b in BANDS}),
                           sample_count=sample.size(), samples=sample.limit(2).toList(2))))
        graph = ee.Dictionary(dict(reference_projection=describe(reference), samples=ee.List(entries)))
        serialized_size = len(graph.serialize())
        response = graph.getInfo()  # One bounded observation evaluation; no bulk extraction.

    comparisons = []
    assert response['reference_projection']['crs'] == inventory['grid_crs']
    assert response['reference_projection']['transform_wkt'] == inventory['grid_transform']
    for (category, row), source in zip(selected, response['samples'], strict=True):
        assert source['sample_count'] == 1, source
        # Image.id() can return the collection-local index rather than asset path.
        assert source['image_id'] in (row['image_id'], DATASET + '/' + row['image_id']), source['image_id']
        assert source['product_date_utc'] == row['product_date_utc']
        values = source['samples'][0]['properties']
        for field in ['pixel_x', 'pixel_y', 'pixel_center_latitude', 'pixel_center_longitude']:
            assert math.isclose(values[field], float(row[field]), rel_tol=0, abs_tol=1e-9), (field, values, row)
        for projection in source['band_projections'].values():
            assert projection == response['reference_projection'], projection
        bands = {}
        for band in BANDS:
            mask = values[band + '_source_mask']
            present = int(row[band + '_present'])
            value = values.get(band)
            agreement = bool(mask > 0) == bool(present) and (
                value == int(row[band]) if present else value is None and int(row[band]) == -9999)
            bands[band] = dict(source_value=value, source_mask=mask,
                               exported_value=int(row[band]), exported_present=present,
                               agreement=agreement)
        agree = all(b['agreement'] for b in bands.values())
        if not agree:
            classification = 'B' if bands['QC_Night']['source_mask'] > 0 and not bands['QC_Night']['exported_present'] else 'D'
        elif bands['QC_Night']['source_mask'] == 0:
            classification = 'A'
        else:
            classification = 'present_preserved_control'
        comparisons.append(dict(category=category, image_id=row['image_id'], date=row['product_date_utc'],
                                pixel_x=values['pixel_x'], pixel_y=values['pixel_y'],
                                latitude=values['pixel_center_latitude'], longitude=values['pixel_center_longitude'],
                                alignment_verified=True, bands=bands, all_bands_agree=agree,
                                classification=classification))
    changed = [name for name, checksum in before.items() if sha(BASE / name) != checksum]
    assert not changed, changed
    result = dict(schema_version='bounded-source-mask-audit/1.0.0',
                  queried_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  project='landslide-1-510217', dataset=DATASET, ee_version=ee.__version__,
                  explicit_observation_evaluations=1, samples_requested=6, serialized_graph_bytes=serialized_size,
                  selection='First and last by product_date_utc, numeric pixel_x, numeric pixel_y, image_id within each category; both LST phases and daytime QC required present/valid.',
                  selection_pools=pools, sampling_region='10 m geodesic buffer around each exported native centre; native projection, no scale override; exactly one returned centre verified',
                  source_csv_sha256=sha(RAW), existing_files_sha256=before,
                  existing_files_unchanged=True, source_response=response, comparisons=comparisons)
    with OUT.open('x') as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps(dict(output=str(OUT), samples=[{k: c[k] for k in ['category', 'image_id', 'pixel_x', 'pixel_y', 'classification', 'all_bands_agree']} for c in comparisons]), indent=2))


if __name__ == '__main__':
    main()

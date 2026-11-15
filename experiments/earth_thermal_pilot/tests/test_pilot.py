"""Offline tests. CSV values below are synthetic test fixtures, never observations."""
import contextlib
import copy
import csv
import io
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

PILOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PILOT))
from common import (BANDS, PILOT_LOCATIONS, STAGES, classify_pixel, decode_qa, decode_time,
                    digest, in_window, load_config, load_locations, within_pilot)
from ee_export import COLUMNS
from pilot import main, plan
from reporting import make_report, pixel_key_coordinate, read_exports, summarize_period, validate_report


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.catalog, self.locations = load_locations(self.config)
        self.config_hash = digest(PILOT / 'config.json')
        self.run_id = 'synthetic_unit_fixture'
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def raw_fixture(self, dates=('2021-01-01',), pixels=2):
        """Deliberately tiny artificial grid for accounting tests only."""
        location = self.locations[0]
        metadata = dict(schema_version='earth-thermal-availability-raw/1.0.0', run_id=self.run_id,
                        dataset_id=self.config['dataset_id'], catalog_sha256=digest(self.catalog),
                        config_sha256=self.config_hash, **location, year=2021, footprint_radius_m=5000)
        rows = [{**metadata, 'record_type': 'partition_inventory', 'image_count': len(dates),
                 'image_dates': '|'.join(dates), 'image_ids': '|'.join('fixture_' + date for date in dates),
                 'native_center_count': pixels, 'native_pixel_keys': '|'.join(f'{x}:0' for x in range(pixels)),
                 'grid_crs': 'synthetic-test-grid', 'grid_transform': '1|0|0|0|-1|0',
                 'requested_footprint_area_m2': 78539816.33974484}]
        for date in dates:
            for x in range(pixels):
                row = {**metadata, 'record_type': 'pixel', 'image_id': 'fixture_' + date,
                       'product_date_utc': date, 'pixel_x': x, 'pixel_y': 0,
                       'pixel_center_latitude': location['canonical_latitude'],
                       'pixel_center_longitude': location['canonical_longitude'], 'native_pixel_area_m2': 1000000}
                for band in BANDS:
                    row[band + '_present'] = 1
                    row[band] = 15000 if band.startswith('LST_') else 0
                row['Day_view_time'] = 140
                row['Night_view_time'] = 20
                rows.append(row)
        return rows

    def write_csv(self, rows, name='synthetic.csv'):
        path = Path(self.temp.name) / name
        with path.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def report(self, rows=None):
        return make_report([self.write_csv(rows if rows is not None else self.raw_fixture())],
                           self.config, self.config_hash, self.run_id)

    def test_exact_canonical_ids_names_coordinates(self):
        raw = json.loads(self.catalog.read_text())
        self.assertEqual([row['location_id'] for row in self.locations], list(PILOT_LOCATIONS))
        for location in self.locations:
            feature = next(feature for feature in raw['features'] if str(feature['id']) == location['location_id'])
            self.assertEqual(location['name'], feature['properties']['name'])
            self.assertEqual(location['canonical_latitude'], feature['properties']['latitude'])
            self.assertEqual(location['canonical_longitude'], feature['properties']['longitude'])

    def test_catalogue_is_not_modified(self):
        before = self.catalog.read_bytes()
        plan(self.config, PILOT / 'config.json')
        self.assertEqual(before, self.catalog.read_bytes())

    def test_plan_has_30_partitions_and_no_remote_execution(self):
        result = plan(self.config, PILOT / 'config.json')
        self.assertEqual(len(result['partitions']), 30)
        self.assertFalse(result['remote_executed'])

    def test_no_network_or_ee_import_for_local_commands(self):
        import builtins
        original = builtins.__import__
        def offline_import(name, *args, **kwargs):
            if name == 'ee' or name.startswith('ee.'):
                raise AssertionError('Local command imported Earth Engine')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=offline_import), patch.object(socket, 'create_connection', side_effect=AssertionError('Network forbidden')):
            for command in [['plan'], ['environment']]:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(command), 0)

    def test_no_samples_means_no_real_report_claim(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = main(['report', '--input-dir', self.temp.name, '--run-id', 'none', '--output', str(PILOT / 'outputs/unused.json')])
        self.assertEqual(code, 2)
        self.assertFalse((PILOT / 'outputs/unused.json').exists())

    def test_time_scale_limits_and_missing(self):
        for raw, expected in [(130, 13.0), (150, 15.0), (10, 1.0), (30, 3.0), (0, 0.0), (240, 0.0), (239, 23.9), (-9999, None), (241, None), (None, None), (True, None)]:
            with self.subTest(raw=raw):
                self.assertEqual(decode_time(raw), expected)

    def test_half_open_and_midnight_windows(self):
        for hour, window, expected in [(13, [13, 15], True), (15, [13, 15], False), (1, [1, 3], True), (3, [1, 3], False), (23.9, [22, 2], True), (0, [22, 2], True), (2, [22, 2], False), (None, [1, 3], False)]:
            with self.subTest(hour=hour):
                self.assertEqual(in_window(hour, window), expected)

    def test_all_256_qa_bytes_decode(self):
        for raw in range(256):
            qa = decode_qa(raw)
            self.assertEqual(list(qa.values()), [(raw >> shift) & 3 for shift in (0, 2, 4, 6)])
        for raw in [-1, 256, None, True, '0']:
            self.assertIsNone(decode_qa(raw))

    def test_individual_criteria_and_qa_profiles(self):
        strict, _, _ = classify_pixel(15000, 0, 140, [13, 15])
        self.assertTrue(strict['strict_qa_in_phase'])
        relaxed, _, _ = classify_pixel(15000, 1 + 16 + 64, 140, [13, 15])
        self.assertFalse(relaxed['strict_qa'])
        self.assertTrue(relaxed['relaxed_qa_in_phase'])
        cloudy, _, _ = classify_pixel(15000, 2, 140, [13, 15])
        self.assertTrue(cloudy['lst_valid'])
        self.assertFalse(cloudy['mandatory_produced'])
        self.assertFalse(cloudy['strict_qa'])

    def test_fill_and_missing_qa_or_time(self):
        for fill in [None, 0, 7499, -9999]:
            self.assertFalse(classify_pixel(fill, 0, 140, [13, 15])[0]['lst_valid'])
        self.assertFalse(classify_pixel(15000, None, 140, [13, 15])[0]['strict_qa'])
        self.assertFalse(classify_pixel(15000, 0, None, [13, 15])[0]['phase_window'])

    def test_distinguishes_pixels_dates_and_raw_observations(self):
        report = self.report()
        validate_report(report, self.config)
        row = report['records'][0]
        self.assertEqual(row['phases']['day']['pixel_retrieval_counts']['lst_valid'], 2)
        self.assertEqual(row['phases']['day']['distinct_product_dates']['lst_valid'], 1)
        self.assertIsNone(report['raw_swath_observation_count'])
        self.assertIsNone(report['effective_independent_observation_count'])
        self.assertEqual(row['exploratory_screen']['status'], 'below_exploratory_screen')
        self.assertEqual(len(report['records']), 390)

    def test_missing_partition_stays_unknown(self):
        report = self.report()
        row = next(row for row in report['records'] if row['location_id'] == '73')
        self.assertEqual(row['input_status'], 'pending_export')
        self.assertIsNone(row['phases'])
        self.assertIsNone(row['source_product_dates'])

    def test_no_source_images_is_explicit_zero_only_with_inventory(self):
        report = self.report(self.raw_fixture(dates=()))
        validate_report(report, self.config)
        row = report['records'][0]
        self.assertEqual(row['source_product_dates'], 0)
        self.assertEqual(row['phases']['night']['pixel_retrieval_counts']['lst_valid'], 0)
        self.assertEqual(len(row['missing_product_dates']), 31)

    def test_masked_retrieval_is_not_qa_zero_match(self):
        rows = self.raw_fixture()
        for band in ['LST_Day_1km', 'Day_view_time']:
            rows[1][band + '_present'] = 0
            rows[1][band] = -9999
        report = self.report(rows)
        validate_report(report, self.config)
        self.assertEqual(report['records'][0]['phases']['day']['pixel_retrieval_counts']['strict_qa_in_phase'], 1)

    def test_truncated_duplicate_or_uninventoried_exports_rejected(self):
        base = self.raw_fixture()
        for rows in [base[:-1], base + [base[1]], base[1:]]:
            with self.subTest(rows=len(rows)):
                with self.assertRaises(ValueError):
                    self.report(rows)

    def test_importing_export_twice_rejected(self):
        path = self.write_csv(self.raw_fixture())
        with self.assertRaises(ValueError):
            read_exports([path, path], self.config, self.config_hash, self.run_id)

    def test_identity_fingerprint_geometry_and_numeric_corruption_rejected(self):
        for key, value in [('location_id', '024'), ('canonical_latitude', 0), ('catalog_sha256', 'bad'), ('config_sha256', 'bad'), ('run_id', 'other'), ('year', 2024), ('native_pixel_area_m2', 'NaN'), ('Day_view_time_present', 2)]:
            rows = self.raw_fixture()
            rows[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.report(rows)

    def test_circular_mean_near_midnight(self):
        rows = self.raw_fixture()
        rows[1]['Night_view_time'] = 239
        rows[2]['Night_view_time'] = 1
        report = self.report(rows)
        validate_report(report, self.config)
        hour = report['records'][0]['phases']['night']['circular_mean_local_solar_hour']
        self.assertTrue(hour < .01 or hour > 23.99)

    def test_same_product_date_support_is_spatial_intersection(self):
        rows = self.raw_fixture()
        rows[1]['Night_view_time'] = 50
        rows[2]['Day_view_time'] = 100
        row = self.report(rows)['records'][0]
        self.assertEqual(row['phases']['day']['pixel_retrieval_counts']['strict_qa_in_phase'], 1)
        self.assertEqual(row['phases']['night']['pixel_retrieval_counts']['strict_qa_in_phase'], 1)
        self.assertEqual(row['same_product_date_joint_strict_phase']['pixel_retrieval_count'], 0)

    def test_schema_and_semantic_validation_reject_bad_output(self):
        original = self.report()
        changes = [lambda r: r.update(raw_swath_observation_count=5),
                   lambda r: r['records'][0]['phases']['day']['pixel_retrieval_counts'].update(strict_qa_in_phase=999),
                   lambda r: r['records'][0].update(location_id='999'),
                   lambda r: r.update(received_partitions=2),
                   lambda r: r['records'][0].update(expected_product_dates=30)]
        for change in changes:
            report = copy.deepcopy(original)
            change(report)
            with self.assertRaises(ValueError):
                validate_report(report, self.config)

    def test_reporting_preserves_opaque_wkt_transform(self):
        rows = self.raw_fixture()
        rows[0]['grid_transform'] = "PARAM_MT[\"Affine\",PARAMETER[\"num_row\",3]]"
        report = self.report(rows)
        validate_report(report, self.config)
        self.assertEqual(report['records'][0]['input_status'], 'complete')

    def test_half_integer_centres_match_inventory_without_changing_counts(self):
        rows = self.raw_fixture(dates=('2021-01-01', '2021-02-01'))
        expected = self.report(copy.deepcopy(rows))
        # Positive MODIS centre coordinates; inventory labels use %.0f.
        rows[0]['native_pixel_keys'] = '11:21|12:21'
        for row in rows[1:]:
            row['pixel_x'] += 10.5
            row['pixel_y'] = 20.5
        actual = self.report(rows)
        validate_report(actual, self.config)
        self.assertEqual(actual['records'], expected['records'])
        self.assertEqual(actual['received_partitions'], 1)
        self.assertEqual(actual['expected_partitions'], 30)
        partitions, _ = read_exports([self.write_csv(rows)], self.config, self.config_hash, self.run_id)
        self.assertEqual(set(partitions[('24', 2021)]['days']['2021-01-01']['pixels']), {(11, 21), (12, 21)})

    def test_pixel_key_conversion_is_not_python_ties_to_even(self):
        for raw, expected in [('14090.5', 14091), ('14091.5', 14092), ('13615.5', 13616),
                              ('-0.5', -1), ('-1.5', -2), ('0', 0), ('12.0', 12)]:
            with self.subTest(raw=raw):
                self.assertEqual(pixel_key_coordinate(raw, 'pixel_x'), expected)

    def test_invalid_fractional_missing_and_nonfinite_coordinates_rejected(self):
        for value in ['14090.25', '14090.500001', 'NaN', 'inf', '-inf', '', None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pixel_key_coordinate(value, 'pixel_x')
            for field in ('pixel_x', 'pixel_y'):
                rows = self.raw_fixture()
                rows[1][field] = value
                with self.subTest(value=value, field=field), self.assertRaises(ValueError):
                    self.report(rows)

    def test_mixed_coordinate_conventions_rejected(self):
        rows = self.raw_fixture()
        rows[1]['pixel_x'] = 0.5
        with self.assertRaises(ValueError):
            self.report(rows)
        rows[1]['pixel_y'] = 0.5
        with self.assertRaises(ValueError):
            self.report(rows)

    def test_half_integer_inventory_mismatch_rejected(self):
        rows = self.raw_fixture()
        for row in rows[1:]:
            row['pixel_x'] += 10.5
            row['pixel_y'] = 20.5
        with self.assertRaisesRegex(ValueError, 'inconsistent native-grid'):
            self.report(rows)

    def test_inventory_blank_pixel_coordinates_are_not_parsed(self):
        rows = self.raw_fixture()
        rows[0]['pixel_x'] = rows[0]['pixel_y'] = ''
        validate_report(self.report(rows), self.config)

    def test_downloaded_atacama_csv_offline_compatibility(self):
        path = PILOT / 'outputs/downloads/tt_avail_availability_pilot_002_24_2021.csv'
        if not path.exists():
            self.skipTest('Optional real Atacama export not downloaded')
        before = digest(path)
        report = make_report([path], self.config, self.config_hash, 'availability_pilot_002')
        validate_report(report, self.config)
        self.assertEqual(report['received_partitions'], 1)
        self.assertEqual(report['expected_partitions'], 30)
        annual = [row for row in report['records'] if row['period_type'] == 'year']
        self.assertEqual(sum(row['input_status'] == 'pending_export' for row in annual), 29)
        complete = next(row for row in annual if row['input_status'] == 'complete')
        self.assertEqual((complete['location_id'], complete['period']), ('24', '2021'))
        self.assertEqual(complete['source_product_dates'], 365)
        self.assertEqual(complete['native_center_count'], 90)
        self.assertEqual(digest(path), before)

    def test_outputs_cannot_escape_pilot_directory(self):
        with self.assertRaises(ValueError):
            within_pilot(PILOT.parents[1] / 'public/data/forbidden.json')


@unittest.skipUnless(importlib.util.find_spec('ee'), 'Installed Earth Engine API required for offline graph checks')
class ExportGraphTests(unittest.TestCase):
    def setUp(self):
        import ee
        from ee import apitestcase
        self.ee = ee
        # Installed API signatures only. No credentials, server calls or task starts.
        for patcher in [
            patch.object(ee.data, '_install_cloud_api_resource', return_value=None),
            patch.object(ee.data, 'getAlgorithms', side_effect=apitestcase.GetAlgorithms),
            patch.object(ee.data, 'computeValue', side_effect=AssertionError('Server evaluation forbidden')),
            patch.object(ee.batch.Task, 'start', side_effect=AssertionError('Export start forbidden')),
            patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)
        ee.Reset()
        self.addCleanup(ee.Reset)
        ee.Initialize(None, '', project='offline-regression')
        from ee_export import build_export
        config = load_config()
        catalogue, locations = load_locations(config)
        location = next(row for row in locations if row['location_id'] == '24')
        self.graph = json.loads(build_export(
            ee, config, location, 2021, 'availability_pilot_002',
            digest(catalogue), digest(PILOT / 'config.json')).serialize())

    def nodes(self, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self.nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from self.nodes(child)

    def test_projection_transform_keeps_its_string_type(self):
        signature = self.ee.ApiFunction.lookup('Projection.transform').getSignature()
        self.assertEqual(signature['returns'], 'String')
        transforms = [node['grid_transform'] for node in self.nodes(self.graph) if 'grid_transform' in node]
        self.assertEqual(len(transforms), 1)
        self.assertEqual(transforms[0]['functionInvocationValue']['functionName'], 'Projection.transform')

    def test_adjacent_inventory_joins_receive_list_expressions(self):
        joins = [node for node in self.nodes(self.graph) if node.get('functionName') == 'List.join']
        self.assertEqual(len(joins), 3)
        for join in joins:
            expression = join['arguments']['list']
            if 'valueReference' in expression:
                expression = self.graph['values'][expression['valueReference']]
            function = expression['functionInvocationValue']['functionName']
            signature = self.ee.ApiFunction.lookup(function).getSignature()
            self.assertTrue(signature['returns'].startswith('List'), function)


if __name__ == '__main__':
    unittest.main()

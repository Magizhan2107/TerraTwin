"""Offline cloud regressions. All generated observations are SYNTHETIC fixtures."""
import contextlib
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

PILOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PILOT))
from common import STAGES, classify_pixel, digest, load_config, load_locations
from cloud_rules import flags, lookup_rules, lst_domain, METRICS, PHASES
from cloud_aggregate import build_compact, PIPELINE, VERSION
from cloud_contract import IDENTITY, SUMMARY, document_from_geojson, hashes, schema, validate
from cloud_compare import compare
from cloud_pilot import main, prepare


class ScalarImage:
    """Minimal mask-preserving scalar EE-image test double for actual flag expressions."""
    def __init__(self,bands):self.bands=bands
    def select(self,names):
        return ScalarImage({k:self.bands[k] for k in ([names] if isinstance(names,str) else names)})
    def mask(self):return ScalarImage({k:(int(m),True) for k,(v,m) in self.bands.items()})
    def unmask(self,value,**kwargs):return ScalarImage({k:(v if m else value,True) for k,(v,m) in self.bands.items()})
    def toInt32(self):return self
    def op(self,other,fn):
        v,m=next(iter(other.bands.values())) if isinstance(other,ScalarImage) else (other,True)
        return ScalarImage({k:(int(fn(x,v)),m and present) for k,(x,present) in self.bands.items()})
    def gt(self,x):return self.op(x,lambda a,b:a>b)
    def gte(self,x):return self.op(x,lambda a,b:a>=b)
    def lte(self,x):return self.op(x,lambda a,b:a<=b)
    def And(self,x):return self.op(x,lambda a,b:bool(a) and bool(b))
    def Not(self):return ScalarImage({k:(int(not v),m) for k,(v,m) in self.bands.items()})
    def remap(self,source,target,default):
        lookup=dict(zip(source,target))
        return ScalarImage({k:(lookup.get(v,default),m) for k,(v,m) in self.bands.items()})
    def value(self):
        v,m=next(iter(self.bands.values()));assert m;return v


class CloudRulesTests(unittest.TestCase):
    def setUp(self):self.config=load_config()
    def run_flags(self,phase,lst,qc,time):
        prefix=phase.title();names=[f'LST_{prefix}_1km',f'QC_{prefix}',prefix+'_view_time']
        return {k:v.value() for k,v in flags(None,ScalarImage({n:(v or 0,v is not None) for n,v in zip(names,[lst,qc,time])}),phase,self.config).items()}
    def test_all_qa_bytes_match_existing_scientific_rules(self):
        for phase,time in [('day',140),('night',20)]:
            for qc in range(256):
                expected=classify_pixel(15000,qc,time,self.config['phase_windows_hours'][phase])[0]
                actual=self.run_flags(phase,15000,qc,time)
                self.assertEqual({k:actual[k] for k in STAGES},{k:int(v) for k,v in expected.items()})
    def test_missing_qc_is_unknown_not_zero(self):
        missing=self.run_flags('night',15000,None,20)
        present_zero=self.run_flags('night',15000,0,20)
        self.assertEqual((missing['lst_valid'],missing['qc_missing'],missing['strict_qa'],missing['relaxed_qa']),(1,1,0,0))
        self.assertEqual((present_zero['qc_missing'],present_zero['strict_qa']),(0,1))
    def test_time_scaling_windows_and_boundaries(self):
        for phase in PHASES:
            for time in [None,0,1,9,10,29,30,129,130,149,150,239,240,241,255]:
                expected=classify_pixel(15000,0,time,self.config['phase_windows_hours'][phase])[0]
                actual=self.run_flags(phase,15000,0,time)
                for k in ['time_valid','phase_window','strict_qa_in_phase','relaxed_qa_in_phase']:
                    self.assertEqual(actual[k],int(expected[k]),(phase,time,k))
    def test_midnight_window_uses_existing_clock_semantics(self):
        self.config=copy.deepcopy(self.config);self.config['phase_windows_hours']['night']=[22,2]
        for time,expected in [(239,1),(0,1),(240,1),(20,0),(10,1),(255,0)]:
            self.assertEqual(self.run_flags('night',15000,0,time)['phase_window'],expected)
    def test_lst_validity_mask_and_scale_domain(self):
        self.assertEqual(lst_domain(),(7500,65535))
        for lst in [None,0,7499,7500,15000,65535,65536]:
            expected=classify_pixel(lst,0,140,[13,15])[0]
            self.assertEqual(self.run_flags('day',lst,0,140)['lst_valid'],int(expected['lst_valid']))
        self.assertEqual(15000*0.02,300) # No temperature rescaling enters availability/QA predicates.
    def test_rare_night_bytes_are_not_strict(self):
        for qc,relaxed in [(65,1),(129,0)]:
            actual=self.run_flags('night',15000,qc,20)
            self.assertEqual((actual['strict_qa'],actual['relaxed_qa']),(0,relaxed))


def synthetic_partition():
    import test_pilot
    maker=test_pilot.PilotTests()
    maker.setUp()
    config=maker.config
    dates=('2021-01-01','2021-02-01')
    raw_rows=maker.raw_fixture(dates=dates)
    raw_path=maker.write_csv(raw_rows)
    from reporting import make_report
    baseline=make_report([raw_path],config,maker.config_hash,maker.run_id)
    fingerprints,scripts=hashes(PILOT/'config.json',config)
    common={**maker.locations[0],**fingerprints,'planet':'Earth','schema_version':VERSION,'pipeline_version':PIPELINE,
            'run_id':'synthetic_cloud_fixture','dataset_id':config['dataset_id'],'source_product_version':'061',
            'footprint_radius_m':5000,'native_grid':'synthetic-test-grid','grid_transform_wkt':'1|0|0|0|-1|0',
            'native_centres':2,'sampled_centre_area_m2':2000000,'requested_footprint_area_m2':78539816.33974484,
            'threshold_status':config['threshold_status'],'mission_suitability':'not_assessed'}
    records=[]
    import calendar
    for m in list(range(1,13))+[None]:
        period='2021' if m is None else f'2021-{m:02d}'
        ds=[d for d in dates if d.startswith(period)];n=len(ds);den=365 if m is None else calendar.monthrange(2021,m)[1]
        r={**common,'period':period,'period_type':'year' if m is None else 'month','calendar_dates':den,
           'source_product_dates':n,'missing_product_dates':den-n,'source_date_fraction':n/den,'pixel_date_records':2*n,
           'source_product_dates_list':'|'.join(ds),'source_image_ids':'|'.join('fixture_'+d for d in ds),
           'unknown_qc_present':0,'joint_pixels':2*n,'joint_dates':n,'joint_supported_dates':n,'joint_mean_calendar_fraction':n/den,
           'coverage_screen':'not_evaluated_year' if m is None else 'below_exploratory_screen',
           'status':'data_available' if m is None else 'insufficient_coverage' if n else 'no_eligible_observations',
           'status_reason':'synthetic fixture only'}
        for phase in PHASES:
            r[phase+'__supported_dates']=n;r[phase+'__supported_calendar_fraction']=n/den
            for metric in METRICS:
                present=metric not in ['qc_missing','time_missing']
                for unit,count in [('pixels',2*n),('dates',n),('centres',2 if n else 0),('calendar_fraction',n/den)]:
                    r[f'{phase}__{metric}__{unit}']=count if present else 0
        records.append(r)
    return maker,{'schema_version':VERSION,'configuration':config,'script_sha256':scripts,'records':records},baseline,raw_path,fingerprints


class CloudContractTests(unittest.TestCase):
    def setUp(self):
        self.maker,self.doc,self.baseline,self.raw,self.hashes=synthetic_partition()
        self.addCleanup(self.maker.doCleanups)
    def test_compact_schema_and_temporal_accounting(self):
        validate(self.doc,self.maker.config,self.hashes)
        year=self.doc['records'][-1]
        self.assertEqual((year['day__lst_valid__pixels'],year['day__lst_valid__dates'],year['day__lst_valid__centres']),(4,2,2))
        self.assertEqual(sum(r['day__lst_valid__pixels'] for r in self.doc['records'][:-1]),year['day__lst_valid__pixels'])
    def test_missing_and_failed_are_not_zero_observations(self):
        for status in ['not_processed','processing_failure']:
            doc=copy.deepcopy(self.doc)
            for r in doc['records']:
                for k in SUMMARY:r.pop(k)
                r.update(status=status,status_reason='explicit unavailable fixture')
            validate(doc,self.maker.config,self.hashes)
            doc['records'][0]['source_product_dates']=0
            with self.assertRaises(ValueError):validate(doc,self.maker.config,self.hashes)
    def test_bad_provenance_coordinates_and_unexpected_fields_rejected(self):
        for k,v in [('config_sha256','0'*64),('catalog_sha256','0'*64),('pipeline_sha256','0'*64),
                    ('canonical_latitude',0),('native_centres',3),('invented_score',99)]:
            doc=copy.deepcopy(self.doc);doc['records'][0][k]=v
            with self.subTest(key=k),self.assertRaises(ValueError):validate(doc,self.maker.config,self.hashes)
    def test_monthly_yearly_mismatch_and_coverage_denominator_rejected(self):
        for key,value in [('day__lst_valid__pixels',99),('source_date_fraction',1),('day__lst_valid__calendar_fraction',1),('status','data_available')]:
            doc=copy.deepcopy(self.doc);doc['records'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate(doc,self.maker.config,self.hashes)
    def test_csv_baseline_comparison_all_counts(self):
        result=compare(self.doc,self.baseline,self.maker.config,self.maker.config_hash,self.raw)
        self.assertTrue(result['passed'],{k:v for k,v in result.items() if k!='matching_fields'})
        self.assertGreater(len(result['matching_fields']),1000)
    def test_comparator_reports_missing_unexpected_and_mismatched_fields(self):
        doc=copy.deepcopy(self.doc)
        doc['records'][0]['night__strict_qa__pixels']=99
        doc['records'][0].pop('night__lst_valid__dates')
        doc['records'][0]['invented_score']=99
        result=compare(doc,self.baseline,self.maker.config,self.maker.config_hash,self.raw)
        self.assertFalse(result['passed'])
        for k in ['missing_fields','unexpected_fields','mismatched_fields']:self.assertTrue(result[k])
    def test_absent_raw_baseline_leaves_extensions_unverified(self):
        result=compare(self.doc,self.baseline,self.maker.config,self.maker.config_hash)
        self.assertFalse(result['passed']);self.assertTrue(result['unverified_fields'])
    def test_geojson_conversion_is_format_only(self):
        manifest={'configuration':self.maker.config,'script_sha256':self.doc['script_sha256']}
        geo={'type':'FeatureCollection','features':[{'type':'Feature','geometry':None,'properties':{**r,'system:index':str(i)}} for i,r in enumerate(self.doc['records'])]}
        self.assertEqual(document_from_geojson(geo,manifest),self.doc)
        for geometry in [{'type':'Point','coordinates':[0,0]},
                         {'type':'MultiPoint','coordinates':[[0,0]]},
                         {'type':'LineString','coordinates':[]},
                         {'type':'MultiPoint','coordinates':None}]:
            geo['features'][0]['geometry']=geometry
            with self.subTest(geometry=geometry),self.assertRaises(ValueError):
                document_from_geojson(geo,manifest)
    def test_empty_multipoint_matches_null_preserving_properties_and_input(self):
        manifest={'configuration':self.maker.config,'script_sha256':self.doc['script_sha256']}
        geo={'type':'FeatureCollection','features':[{'type':'Feature',
            'geometry':None if i % 2 else {'type':'MultiPoint','coordinates':[]},
            'properties':copy.deepcopy(r)} for i,r in enumerate(self.doc['records'])]}
        before=copy.deepcopy(geo)
        converted=document_from_geojson(geo,manifest)
        self.assertEqual(converted,self.doc)
        self.assertEqual(converted['records'],[f['properties'] for f in before['features']])
        self.assertEqual(geo,before)
    def test_published_schema_matches_contract(self):
        self.assertEqual(json.loads((PILOT/'cloud.diagnostic.schema.json').read_text()),schema())
    def test_bounded_real_cloud_evidence_matches_schema_when_available(self):
        path=PILOT/'outputs/cloud_atacama_two_date_check_001.json'
        if not path.exists():self.skipTest('Optional bounded verification evidence not present')
        evidence=json.loads(path.read_text())
        self.assertEqual(evidence['matched_fields'],135)
        self.assertEqual(evidence['mismatches'],[])
        self.assertFalse(evidence['export_submitted'])
        from jsonschema import Draft202012Validator
        Draft202012Validator(schema()['properties']['records']['items']).validate(evidence['cloud_january_summary_for_two_source_dates_only'])
    def test_existing_cloud_intent_blocks_submission_before_remote_init(self):
        with tempfile.TemporaryDirectory(dir=PILOT/'outputs') as name:
            root=Path(name);directory=root/'outputs/cloud/tasks';directory.mkdir(parents=True)
            intent=directory/'duplicate_24_2021.prepared.json';intent.write_text('preserved audit fixture')
            with patch('cloud_pilot.PILOT_DIR',root),patch('cloud_pilot.initialize',side_effect=AssertionError('Must not initialize or submit')):
                with contextlib.redirect_stderr(io.StringIO()):
                    code=main(['--config',str(PILOT/'config.json'),'submit','--project','landslide-1-510217',
                               '--location-id','24','--year','2021','--run-id','duplicate'])
            self.assertEqual(code,2)
            self.assertEqual(intent.read_text(),'preserved audit fixture')
    def test_offline_plan_requires_no_network_and_retains_catalogue(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')):
            plan=prepare(PILOT/'config.json','24',2021,'thermal_cloud_validation_001')
        self.assertEqual(plan['location'],self.maker.locations[0])
        self.assertEqual(plan['export_tasks'],1)
        self.assertEqual(len(plan['catalogue_partitions']),30)
        self.assertTrue(all(r['status']=='not_processed' and r['observation_counts'] is None for r in plan['catalogue_partitions']))
        self.assertFalse(plan['remote_executed'])


@unittest.skipUnless(importlib.util.find_spec('ee'),'Installed EE API needed for offline graph checks')
class CloudGraphTests(unittest.TestCase):
    def setUp(self):
        import ee
        from ee import apitestcase
        self.ee=ee
        for patcher in [patch.object(ee.data,'_install_cloud_api_resource',return_value=None),
                        patch.object(ee.data,'getAlgorithms',side_effect=apitestcase.GetAlgorithms),
                        patch.object(ee.data,'computeValue',side_effect=AssertionError('No server evaluation')),
                        patch.object(ee.batch.Task,'start',side_effect=AssertionError('No task starts')),
                        patch.object(socket.socket,'connect',side_effect=AssertionError('No network'))]:
            patcher.start();self.addCleanup(patcher.stop)
        ee.Reset();self.addCleanup(ee.Reset);ee.Initialize(None,'',project='offline-cloud-tests')
        config=load_config();_,locations=load_locations(config);fingerprints,_=hashes(PILOT/'config.json',config)
        self.graph=json.loads(build_compact(ee,config,locations[0],2021,'synthetic_graph_only',fingerprints).serialize())
    def nodes(self,x):
        if isinstance(x,dict):
            yield x
            for v in x.values():yield from self.nodes(v)
        elif isinstance(x,list):
            for v in x:yield from self.nodes(v)
    def test_actual_graph_serializes_and_uses_cloud_aggregation(self):
        functions={n['functionName'] for n in self.nodes(self.graph) if 'functionName' in n}
        self.assertTrue({'Image.reduceRegion','Reducer.unweighted','reduce.sum','Collection.reduceColumns'}<=functions,functions)
        self.assertNotIn('Image.sample',functions) # No raw pixel-date table is built/exported.
    def test_native_grid_no_scale_override_or_best_effort(self):
        reducers=[n for n in self.nodes(self.graph) if n.get('functionName')=='Image.reduceRegion']
        self.assertTrue(reducers)
        for r in reducers:
            self.assertIn('crs',r['arguments'])
            self.assertNotIn('scale',r['arguments']);self.assertNotIn('bestEffort',r['arguments'])
        text=json.dumps(self.graph)
        self.assertIn('Projection.transform',text)
        self.assertNotIn('Number.round',text)
    def test_thirteen_summary_periods_and_mask_rules_in_graph(self):
        text=json.dumps(self.graph)
        for label in ['2021-01','2021-12','2021','day__qc_missing__pixels','night__strict_qa_in_phase__dates','no_eligible_observations']:
            self.assertIn(label,text)
        self.assertIn('Image.remap',text);self.assertIn('Image.mask',text)


if __name__=='__main__':unittest.main()

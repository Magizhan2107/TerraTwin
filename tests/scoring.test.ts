import { describe, expect, it } from 'vitest';
import { rankCandidates, scoreTerrain } from '../src/modules/roverMobility/scoring';
import { parseTerrain, validateDatasets } from '../src/services/datasets';
const target = { id:'gale', name:'Gale', latitude:-5.4,longitude:137.8,mean_slope_deg:6,p90_slope_deg:15,roughness_mean_m:20,elevation_stddev_m:300 };
describe('deterministic fixed-scale scoring',()=>{
 it('returns 100 for identical terrain',()=>expect(scoreTerrain(target,target).similarityScore).toBe(100));
 it('uses equal weights and fixed scales',()=>expect(scoreTerrain(target,{...target,mean_slope_deg:21}).similarityScore).toBe(87.5));
 it('clamps each feature difference',()=>expect(scoreTerrain(target,{...target,mean_slope_deg:36,p90_slope_deg:60,roughness_mean_m:120,elevation_stddev_m:1300}).similarityScore).toBe(0));
 it('supports hundreds of candidates and deterministic tie ordering',()=>{const candidates=Array.from({length:300},(_,i)=>({...target,id:`site-${String(i).padStart(3,'0')}`}));expect(rankCandidates(target,candidates.reverse())).toHaveLength(300);expect(rankCandidates(target,candidates)[0].earthCandidateId).toBe('site-000');});
 it('is independent of other candidates',()=>{const a={...target,id:'a',mean_slope_deg:12};expect(rankCandidates(target,[a])[0].similarityScore).toBe(rankCandidates(target,[a,target]).find(r=>r.earthCandidateId==='a')?.similarityScore);});
});
describe('data validation',()=>{
 it.each([null,undefined,NaN,Infinity,'6',-1])('rejects invalid measurements %s',value=>expect(parseTerrain({...target,mean_slope_deg:value},'x')).toBeNull());
 it('rejects invalid coordinates and slopes',()=>{expect(parseTerrain({...target,latitude:91},'x')).toBeNull();expect(parseTerrain({...target,p90_slope_deg:4},'x')).toBeNull();});
 it('excludes invalid and duplicate candidates',()=>{const features=[target,{...target,mean_slope_deg:null},target].map(properties=>({type:'Feature',properties}));const data=validateDatasets(target,{type:'FeatureCollection',features});expect(data.candidates).toHaveLength(1);expect(data.excluded).toBe(2);expect(data.provenance[0].demonstration).toBe(true);});
 it('rejects malformed datasets',()=>{expect(()=>validateDatasets({},{})).toThrow();expect(()=>validateDatasets(target,{type:'FeatureCollection'})).toThrow();});
 it('handles empty candidate sets',()=>expect(validateDatasets(target,{type:'FeatureCollection',features:[]}).candidates).toEqual([]));
});

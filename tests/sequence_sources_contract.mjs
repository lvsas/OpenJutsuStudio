import assert from 'node:assert/strict';
import {test} from 'node:test';
import {isSwap,sourceId,sourceKind,sourceKey,sourceLabel,sourceDuration} from '../src/static/sequence-sources.js';
import {emptyWorkspace,addPlacement,movePlacement,removePlacement,saveDraft} from '../src/static/sequence-state.js';
const A='a'.repeat(32),P='1'.repeat(32),Q='2'.repeat(32);
const native={take:{take_id:A,family:{context:{delivered_frames:120,fps:24}},lineage:{relation:'root',parent_id:null}}};
const swap={kind:'swap',job:{job_id:A,engine:'minimax-h3',status:'done',created:'2026-01-01'},media_url:`/api/jobs/${A}/result`};
test('typed identities distinguish native and Swap with the same UUID without fabricated Takes',()=>{
  assert.equal(isSwap(swap),true);assert.equal(isSwap(native),false);
  assert.equal(sourceId(native),A);assert.equal(sourceId(swap),A);
  assert.equal(sourceKind(native),'native');assert.equal(sourceKind(swap),'swap');
  assert.equal(sourceKey(native),`native:${A}`);assert.equal(sourceKey(swap),`swap:${A}`);
  assert.equal('take' in swap,false);
});
test('source labels preserve native names and never invent Swap durations',()=>{
  assert.equal(sourceLabel(native),'Take · 5.0 s');
  assert.equal(sourceLabel(swap),'H3 Swap');assert.equal(sourceDuration(swap),null);
  assert.equal(sourceLabel({...swap,job:{...swap.job,engine:'ltx25-ripple'}}),'LTX Swap');
  assert.equal(sourceDuration(native),5);
  assert.equal(sourceDuration({...native,take:{...native.take,family:{context:{fps:0,delivered_frames:120}}}}),null);
  assert.equal(sourceLabel(null),'Unavailable take');
});
test('placements serialize explicit Swap kind, omit native defaults and preserve typed identities through edits',()=>{
  let state=addPlacement(emptyWorkspace(),A,P,null,'swap');
  state=saveDraft(state,P,{prompt:'Retained',seed:'18446744073709551615'});
  state=addPlacement(state,A,Q);
  assert.deepEqual(state.placements,[{placement_id:P,take_id:A,source_kind:'swap'},{placement_id:Q,take_id:A}]);
  state=JSON.parse(JSON.stringify(movePlacement(state,Q,-1)));
  assert.equal(state.placements[1].source_kind,'swap');assert.equal(state.drafts[P].prompt,'Retained');
  assert.equal(removePlacement(state,Q).placements[0].source_kind,'swap');
  assert.throws(()=>addPlacement(emptyWorkspace(),A,P,null,'invented'),/source kind/i);
});

import assert from 'node:assert/strict';
import {test} from 'node:test';
import {emptyWorkspace, addPlacement, removePlacement, movePlacement, saveDraft,
        forwardBody, exactSeed} from '../src/static/sequence-state.js';
const A = 'a'.repeat(32), B = 'b'.repeat(32), P = '1'.repeat(32), Q = '2'.repeat(32);
test('placements are intentional, can reuse a Take, and never invent ancestry', () => {
  const original = emptyWorkspace();
  const one = addPlacement(original, A, P);
  const two = addPlacement(one, A, Q);
  assert.equal(original.placements.length, 0);
  assert.deepEqual(two.placements, [{placement_id:P,take_id:A},{placement_id:Q,take_id:A}]);
  assert.equal(two.selected_placement_id, Q);
  assert.equal('parent_id' in two.placements[1], false);
});
test('remove/reorder preserve other drafts and do not mutate Takes', () => {
  let state = addPlacement(addPlacement(emptyWorkspace(), A, P), B, Q);
  state = saveDraft(state, P, {prompt:'Keep moving',seed:'18446744073709551615',raw_frames:158});
  state = movePlacement(state,Q,-1);
  assert.equal(state.placements[0].placement_id,Q);
  state = removePlacement(state,Q);
  assert.equal(state.selected_placement_id,P);
  assert.equal(state.drafts[P].prompt,'Keep moving');
  assert.deepEqual(state.placements,[{placement_id:P,take_id:A}]);
});
test('each placement has an independent draft even when the Take is reused', () => {
  let state = addPlacement(addPlacement(emptyWorkspace(), A, P), A, Q);
  state = saveDraft(state,P,{prompt:'First'});
  assert.equal(state.drafts[Q].prompt,'');
  assert.equal(state.drafts[P].prompt,'First');
});
test('exact seeds survive numeric JSON without a JS Number roundtrip', () => {
  const seed='18446744073709551615';
  const body=forwardBody({request_id:A,prompt:'Keep the motion',seed,raw_frames:158});
  assert.match(body,/"seed":18446744073709551615/);
  assert.equal(body.includes('18446744073709552000'),false);
  assert.equal(JSON.parse(body).prompt,'Keep the motion');
  assert.equal(exactSeed('0'),'0');
  for(const bad of ['18446744073709551616','1e5','-1','abc','',Number.MAX_SAFE_INTEGER]) {
    assert.throws(()=>exactSeed(bad));
  }
});
test('invalid identities and orphan draft edits are refused',()=>{
  assert.throws(()=>addPlacement(emptyWorkspace(),'../../x',P));
  assert.throws(()=>saveDraft(emptyWorkspace(),P,{prompt:'orphan'}));
});

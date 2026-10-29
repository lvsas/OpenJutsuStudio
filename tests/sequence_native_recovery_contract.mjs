import assert from 'node:assert/strict';
import {test} from 'node:test';
import {nativeVersionsForSwap,mergeSequenceLibrary} from '../src/static/sequence-library.js';
import {createDurationPicker} from '../src/static/continuity-duration.js';
const J='a'.repeat(32),T='b'.repeat(32),OTHER='d'.repeat(32);
test('one creation resolves to its real saved take without a competing finished-video source',()=>{
 const paired={take:{take_id:T,origin:{source_job:J}}};
 const rows=[{job_id:J,engine:'minimax-h3',status:'done',native_take_id:T,native_artifact_relation:'native-raw-family-and-distinct-finished-swap'}];
 const entries=mergeSequenceLibrary([paired],rows);
 assert.equal(entries.length,1);assert.equal(entries[0].take.take_id,T);
 assert.deepEqual(nativeVersionsForSwap(entries,J),entries);
 const collision={take:{take_id:J,origin:{source_job:'unrelated'}}};
 assert.deepEqual(nativeVersionsForSwap([collision],J),[]);
 assert.deepEqual(nativeVersionsForSwap(entries,'../unsafe'),[]);
 assert.equal(nativeVersionsForSwap([...entries,{take:{take_id:OTHER,origin:{source_job:J}}}],J).length,2,'Actual ambiguous versions are never guessed');
 assert.equal(paired.project_job_ids,undefined,'Discovery never mutates the original record');
});
test('a video-only refusal is not reported as a failed HTTP request',()=>{
 globalThis.Option=class{constructor(text,value){this.text=text;this.value=value;}};
 const select={value:'277',disabled:false,replaceChildren(...x){this.options=x;},addEventListener(){}};
 const hint={textContent:''},picker=createDurationPicker(select,hint);
 picker.ready({available:false,mode:'forward',reason_code:'video_only',duration_options:[]});
 assert.match(hint.textContent,/video|saved state/i);assert.doesNotMatch(hint.textContent,/request failed/i);assert.equal(select.disabled,true);
 picker.unavailable();assert.match(hint.textContent,/request failed/i);
});

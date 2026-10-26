import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const elements=new Map();
class Element {
  constructor(){this.hidden=true;this.children=[];this.textContent='';this.attrs={};}
  addEventListener(name,fn){this[name]=fn;}
  removeAttribute(name){delete this[name];}
  append(child){this.children.push(child);}
  replaceChildren(){this.children=[];}
}
const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
globalThis.document={getElementById:el,createElement:()=>new Element()};
globalThis.window={};globalThis.localStorage={getItem:()=>null};
const {H3Take}=await import('../src/static/h3-take.js');
const job='a'.repeat(32),id='b'.repeat(32),root=`/api/continuity/takes/${id}`;
const data={available:true,take_id:id,native_seconds:8.5,display_seconds:6,
  relation:'native-raw-family-and-distinct-finished-swap',urls:{video:`${root}/artifacts/video`,mctx:`${root}/artifacts/mctx`,conditioning:`${root}/artifacts/conditioning`,preview:`${root}/media`,capsule:`${root}/capsule`,timeline:`/timeline?job_id=${job}`}};
const take=new H3Take(()=>{},async()=>true);take.id=job;
const calls=[];let handler=async()=>data;
globalThis.fetch=async(url,options)=>{calls.push([url,options]);return {ok:true,json:handler};};
await take.loadNativeState(take.epoch);
assert.equal(calls.length,0,'Old jobs do not request missing native state');
take.job={meta:{native_take_id:'../unsafe'}};await take.loadNativeState(take.epoch);assert.equal(calls.length,0);
take.job={meta:{native_take_id:id}};await take.loadNativeState(take.epoch);
assert.equal(el('h3-native-state').hidden,false);assert.match(el('h3-native-seconds').textContent,/8.5 s.*6 s/);
assert.equal(el('h3-native-video').href,data.urls.video);
assert.deepEqual(calls.map(([url])=>url),[`/api/h3/jobs/${job}/native-state`],'No media bytes or downloads are requested');
for(const key of Object.keys(data.urls)){
  for(const unsafe of ['https://evil.example/file','//evil.example/file','/api/continuity/takes/'+'c'.repeat(32)+'/media']){
    handler=async()=>({...data,urls:{...data.urls,[key]:unsafe}});
    await take.loadNativeState(take.epoch);assert.equal(el('h3-native-state').hidden,true,`${key} rejects unsafe URL`);
    assert.equal(el('h3-native-video').href,undefined);
    assert.match(el('h3-native-state-status').textContent,/could not be verified/);
    assert.ok(!el('h3-native-state-status').textContent.includes('evil.example'));
  }
}
handler=async()=>({available:false});await take.loadNativeState(take.epoch);assert.equal(el('h3-native-state').hidden,true);
let release;handler=()=>new Promise(resolve=>{release=resolve;});
const pending=take.loadNativeState(take.epoch);await Promise.resolve();
take.epoch++;take.clearNativeState();release(data);await pending;
assert.equal(el('h3-native-state').hidden,true,'Late state cannot resurrect the reset panel');
const parent={job_id:job,recipe:{native_capture:false}};
take.capsule=parent;take.watch=child=>{assert.equal(child,'c'.repeat(32));take.active=false;};
for(const checked of [true,false]){
  el('h3-native-capture').checked=checked;
  handler=async()=>({job_id:'c'.repeat(32)});
  await take.replay();
  const [url,options]=calls.at(-1);
  assert.equal(url,`/api/h3/jobs/${job}/replay`);
  assert.deepEqual(JSON.parse(options.body),{native_capture:checked});
  assert.equal(parent.recipe.native_capture,false,'Replay option never changes parent recipe');
  assert.equal(el('h3-native-capture').checked,checked,'Past take does not reset a newer draft');
}
// Exercise the actual handoff function with bounded dependencies, not a copied implementation.
const source=readFileSync(new URL('../src/static/continuity-studio.js',import.meta.url),'utf8');
const body=source.slice(source.indexOf('async function openLinkedSwap('),source.indexOf("byId('native-handoff-add').addEventListener"));
const {mergeSequenceLibrary}=await import('../src/static/sequence-library.js');
const native={take:{take_id:id,origin:{source_job:job},family:{context:{delivered_frames:204,fps:24}}}};
const entries=mergeSequenceLibrary([native],[{job_id:job,engine:'minimax-h3',status:'done',native_take_id:id,native_artifact_relation:data.relation}]);
for(const chosen of [0,1]){
  elements.clear();let selected=null;const state={epoch:1};
  const sequence={state:()=>({project_id:'c'.repeat(32)}),editable:()=>true};
  const make=new Function('entries','byId','document','sequence','state','isSwap','sourceId','showLinkedNative','showLinkedVideo',
    `let linkedTake=null,inFlight=false,unconfirmed=false;const updateComposer=()=>{},notice=()=>{};${body.replaceAll('token=epoch','token=state.epoch').replaceAll('token===epoch','token===state.epoch')};return openLinkedSwap;`);
  const open=make(entries,el,document,sequence,state,e=>e.kind==='swap',e=>e.job?.job_id,
    e=>{selected=['native',e.take.take_id];},e=>{selected=['swap',e.job.job_id];});
  const before=calls.length;await open(job);
  assert.equal(selected,null,'No version is silently chosen');
  const buttons=el('native-handoff-choices').children;
  assert.deepEqual(buttons.map(b=>b.textContent),['Finished Swap','Native state version · 8.5 s']);
  assert.match(el('native-handoff-message').textContent,/original timing and source audio.*full sampled duration and generated audio/);
  assert.equal(calls.length,before,'Navigation performs no inference or media request');
  if(chosen===0){state.epoch++;buttons[0].click();assert.equal(selected,null,'Obsolete choice is ignored');state.epoch--;}
  buttons[chosen].click();assert.deepEqual(selected,chosen===0?['swap',job]:['native',id]);
}
console.log('H3 native state: safe URLs, opt-in discovery, no byte fetch, late reset and explicit distinct-version choice passed');

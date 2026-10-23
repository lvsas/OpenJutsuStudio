// Shipped ES modules run in isolated DOMs. Fixtures below are unit-test responses,
// not evidence of browser layout, valid decoded video, OS sharing or backend writes.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {resolve, dirname} from 'node:path';
import {File} from 'node:buffer';
import {randomUUID,webcrypto} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const A='a'.repeat(32), B='b'.repeat(32), C='c'.repeat(32);
const clip=(id,start,end)=>({clip_id:id,take_id:id,label:'A take',engine:'ltx25-ripple',
  width:96,height:48,fps:24,frames:288,in_frame:start,out_frame:end,
  media_url:`/api/timeline/takes/${id}/media`,source_job_id:null});
const project=()=>({project_id:A,title:'My cut',revision:1,character_id:null,
  clips:[clip(B,120,240),clip(C,24,48)]});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const flush=async()=>{for(let i=0;i<20;i++) await new Promise(r=>setImmediate(r));};
const response=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
class Element {
  constructor(){this.listeners={};this.children=[];this.style={};this.dataset={};this.attributes={};
    this.hidden=false;this.disabled=false;this.paused=true;this.readyState=1;this.currentTime=0;
    this.clientWidth=400;this._value='';this.open=false;this.classList={add(){},remove(){}};}
  set value(value){this._value=String(value);} get value(){return this._value;}
  set textContent(value){this.text=String(value);this.children=[];} get textContent(){return this.text||'';}
  set innerHTML(_){throw Error('Unsafe DOM assignment');}
  addEventListener(event,fn){(this.listeners[event]||=[]).push(fn);}
  async fire(event,extra={}){for(const fn of this.listeners[event]||[]) await fn({target:this,preventDefault(){},...extra});}
  append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=String(value);} getAttribute(key){return key==='src'?this.src||null:this.attributes[key]??null;}
  removeAttribute(key){delete this.attributes[key];if(key==='src')this.src='';}
  pause(){this.paused=true;void this.fire('pause');}
  play(){this.paused=false;return this.fire('play');}
  load(){this.loadCount=(this.loadCount||0)+1;if(this.src)queueMicrotask(()=>this.onloadedmetadata?.());}
  close(){this.open=false;void this.fire('close');} showModal(){this.open=true;}
  querySelectorAll(){return [];}
  focus(){} select(){} click(){return this.fire('click');}
}
async function environment(fetcher,search='',initialStorage={}) {
  const markup=readFileSync(resolve(root,'src/templates/timeline.html'),'utf8');
  const elements=new Map([...markup.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)].map(([tag,id])=>{
    const element=new Element();element.hidden=/\bhidden(?:\s|>|=)/.test(tag);return [id,element];
  }));
  const notices=[],events={},storage=new Map(Object.entries(initialStorage));const location={search,href:'http://test.invalid/timeline'};
  const document={getElementById:id=>elements.get(id),createElement:()=>new Element()};
  const context=vm.createContext({document,location,console,URLSearchParams,URL,Response,File,
    Blob,AbortSignal,queueMicrotask,fetch:fetcher,setTimeout,clearTimeout,structuredClone,
    crypto:{randomUUID,getRandomValues:a=>webcrypto.getRandomValues(a)},
    Option:class extends Element{constructor(text,value){super();this.textContent=text;this.value=value;}},
    navigator:{share:async()=>{},canShare:()=>true},
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    history:{replaceState:(_,__,url)=>{location.search=new URL(url,'http://test.invalid').search;}},
    window:{addEventListener:(event,fn)=>{(events[event]||=[]).push(fn);},
      OpenGenjutsuStudio:{showToast:(_,text)=>notices.push(text)}}});
  const modules=new Map();
  async function load(path){
    path=resolve(path);if(modules.has(path))return modules.get(path);
    const module=new vm.SourceTextModule(readFileSync(path,'utf8'),{context,identifier:path});
    modules.set(path,module);await module.link((specifier,parent)=>load(resolve(dirname(parent.identifier),specifier)));
    return module;
  }
  async function entry(name){const module=await load(resolve(root,'src/static',name));await module.evaluate();return module.namespace;}
  return {elements,notices,entry,storage,events};
}

test('positions use ordered placement identities and refuse a changed gap',async()=>{
  const app=await environment(()=>{throw Error('Position arithmetic must not fetch');});
  const {positionsOf,resolvePosition,insertAtPosition}=await app.entry('sequence-positions.js');
  const state={placements:[{placement_id:A,take_id:A},{placement_id:B,take_id:B}],
    selected_placement_id:A,drafts:{[A]:{prompt:'Keep my draft',seed:'18446744073709551615',raw_frames:158}}};
  const original=JSON.stringify(state),gaps=positionsOf(state);
  assert.deepEqual(Array.from(gaps,p=>p.mode),['prepend','bridge','forward']);
  for(const [index,gap] of Array.from(gaps).entries()) {
    const next=insertAtPosition(state,A,C,gap);
    assert.equal(next.placements[index].placement_id,C);
    assert.equal(JSON.stringify(next.drafts[A]),JSON.stringify(state.drafts[A]));
  }
  assert.equal(JSON.stringify(state),original);
  assert.throws(()=>resolvePosition({...state,placements:[...state.placements].reverse()},gaps[1]),/position changed/i);
  assert.throws(()=>resolvePosition(state,{left:'../bad',right:null}),/current empty slot/i);
  assert.equal(positionsOf({placements:[]})[0].mode,'root');
});

test('position drafts survive mode switching and cannot move with stale anchors',async()=>{
  const app=await environment(()=>{throw Error('Pure drafts do not fetch');});
  const {positionsOf,selectPosition,savePositionDraft,positionFromKey}=await app.entry('sequence-positions.js');
  let state={placements:[{placement_id:A,take_id:A},{placement_id:B,take_id:B}],drafts:{},position_drafts:{}};
  const gap=positionsOf(state)[1];
  state=selectPosition(state,gap);
  state=savePositionDraft(state,{prompt:'Connect these moments',seed:'18446744073709551615'});
  const bridge=state.selected_position;
  state=selectPosition(state,gap,{mode:'root'});
  state=savePositionDraft(state,{prompt:'Independent new scene',reference_ids:[C]});
  state=selectPosition(state,gap);
  assert.equal(state.selected_position,bridge);
  assert.equal(state.position_drafts[bridge].prompt,'Connect these moments');
  assert.equal(state.position_drafts[bridge].seed,'18446744073709551615');
  assert.equal(Object.keys(state.position_drafts).length,2);
  assert.throws(()=>positionFromKey({...state,placements:[]},bridge),/position changed/i);
});

test('empty creation slot and exact drops never generate or overwrite drafts',async()=>{
  const saved={project_id:C,title:'Positions',revision:1,placements:[{placement_id:A,take_id:A},{placement_id:B,take_id:B}],
    selected_placement_id:A,drafts:{[A]:{prompt:'Original',seed:'18446744073709551615',raw_frames:158}}};
  const backend=nativeBackend({saved}),app=await environment(backend.fetcher,'',{'opengenjutsu.sequence.project':C}),picked=[];
  const {mountSequence}=await app.entry('sequence-workspace.js');
  const seq=mountSequence({onSelect(){},onPreview(){},onCompose(){},onPosition:p=>picked.push(p),onError:assert.fail});
  await seq.init([nativeEntry(A),nativeEntry(B)]);
  const rail=app.elements.get('board-track');
  assert.equal(rail.children.length,5,'three actionable positions around two retained takes');
  await rail.children[2].children[0].click();
  assert.equal(picked.at(-1).mode,'bridge');
  await rail.children[0].fire('drop',{dataTransfer:{getData:()=>B}});
  await seq.flush();
  assert.deepEqual(Array.from(seq.state().placements,p=>p.take_id),[B,A,B]);
  assert.equal(seq.state().drafts[A].prompt,'Original');
  assert.equal(seq.state().drafts[A].seed,'18446744073709551615');
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')),false);
});

test('native seeking/play cannot replay trimmed-away prefix; sequence still advances',async()=>{
  const app=await environment(()=>{throw Error('No network in player');});
  const {SequencePlayer}=await app.entry('timeline-player.js');
  const video=app.elements.get('timeline-video');const selected=[];
  const player=new SequencePlayer(video,{onSelect:value=>selected.push(value.clip_id)});
  const clips=project().clips;player.setClips(clips,B);await flush();
  player.playSequence();await flush();
  video.currentTime=0;await video.fire('seeking');
  assert.equal(video.currentTime,clips[0].in_frame/clips[0].fps,'native seek must respect the retained start');
  video.currentTime=1;await video.play();
  assert.equal(video.currentTime,clips[0].in_frame/clips[0].fps,'native play must not escape the trim');
  video.currentTime=clips[0].out_frame/clips[0].fps;await video.fire('timeupdate');await flush();
  assert.equal(player.index,1);assert.equal(selected.at(-1),C);assert.equal(video.currentTime,clips[1].in_frame/clips[1].fps);
  video.currentTime=clips[1].out_frame/clips[1].fps;await video.fire('timeupdate');
  assert.equal(video.paused,true);assert.equal(player.sequenceMode,false);
});

test('reopening export resets sharing lock and rejects obsolete prepared file',async()=>{
  const oldDownload=deferred();let exports=0;
  const app=await environment(async url=>{
    if(url.endsWith('/export')){const id=++exports===1?B:C;return response({export_id:id,project_id:A,revision:exports,status:'ready',
      status_url:`/api/timeline/exports/${id}`,preview_url:`/api/timeline/exports/${id}/media`,download_url:`/api/timeline/exports/${id}/media?download=true`});}
    if(url===`/api/timeline/exports/${B}/media`)return oldDownload.promise;
    throw Error(`Unexpected request: ${url}`);
  });
  const {TimelineExport}=await app.entry('timeline-export-ui.js');
  const ui=new TimelineExport(text=>app.notices.push(text));await ui.open(project());
  const preparation=ui.share();assert.equal(app.elements.get('share-export').disabled,true);
  app.elements.get('timeline-export-dialog').close();
  try {
    await ui.open({...project(),revision:2});
    assert.equal(app.elements.get('share-export').disabled,false,'obsolete download must not lock the new export');
  } finally {
    oldDownload.resolve(new Response(new Uint8Array([1,2,3]),{headers:{'Content-Type':'video/mp4'}}));
    await preparation;
  }
  assert.equal(ui.current.export_id,C);assert.equal(ui.file,null);
  assert.equal(app.elements.get('share-export').disabled,false);
  assert.ok(!app.notices.some(text=>text.startsWith('File prepared.')));
});

test('reload cannot start or release editor locks while save PATCH is pending',async()=>{
  const patch=deferred();const calls=[];let saved=project();
  const app=await environment(async(url,options={})=>{
    calls.push({url,method:options.method||'GET'});
    if(url==='/api/jobs')return response([]);
    if(url==='/api/timeline/projects')return response({projects:[{project_id:A,title:saved.title}]});
    if(url===`/api/timeline/projects/${A}`){
      if(options.method==='PATCH'){await patch.promise;saved={...saved,title:JSON.parse(options.body).title,revision:2};return response(saved);}
      return response(saved);
    }
    throw Error(`Unexpected request: ${url}`);
  },`?project_id=${A}`);
  await app.entry('timeline.js');await flush();
  const e=app.elements;await e.get('timeline-video').fire('error');
  assert.equal(e.get('reload-project').hidden,false);
  const gets=()=>calls.filter(call=>call.url===`/api/timeline/projects/${A}`&&call.method==='GET').length;
  const before=gets();e.get('project-title').value='A new name';
  const saving=e.get('save-title').fire('click');await flush();
  try {
    await e.get('reload-project').fire('click');await flush();
    assert.equal(gets(),before,'Reload must not issue a competing project GET');
    assert.equal(e.get('reload-project').disabled,true);
    assert.equal(e.get('project-title').disabled,true);
    assert.equal(e.get('save-status').textContent,'Saving…');
  } finally {patch.resolve();await saving;await flush();}
  assert.equal(e.get('project-title').value,'A new name');assert.equal(e.get('project-title').disabled,false);
  assert.equal(e.get('save-status').textContent,'All changes saved');
});

const nativeEntry=id=>({take:{take_id:id,family:{context:{width:1280,height:704,
  delivered_frames:89,fps:24}},lineage:{parent_id:null},recipe:{availability:'captured_execution_graph'}},
  media_url:`/api/continuity/takes/${id}/media`,capsule_url:`/api/continuity/takes/${id}/capsule`});
function nativeBackend({saved=null,extra=null}={}) {
  const calls=[];let current=saved;
  const fetcher=async(url,options={})=>{
    calls.push({url,method:options.method||'GET',body:options.body});
    if(url==='/api/continuity/takes')return response({takes:[nativeEntry(A),nativeEntry(B)]});
    if(extra){const value=await extra(url,options);if(value)return value;}
    if(url.endsWith('/readiness'))return response({verified:true,extend:true,reason:null,duration_options:[{raw_frames:158,seconds:5.125},{raw_frames:226,seconds:191/24},{raw_frames:277,seconds:242/24},{raw_frames:328,seconds:293/24},{raw_frames:396,seconds:361/24}]});
    if(url.endsWith('/references'))return response({references:[{index:1}]});
    if(url==='/api/timeline/projects'&&options.method==='POST') {
      current={project_id:C,title:JSON.parse(options.body).title,revision:0,
        placements:[],selected_placement_id:null,drafts:{}};return response(current);
    }
    if(url==='/api/timeline/projects')return response({projects:current?[current]:[]});
    if(url===`/api/timeline/projects/${C}/native-workspace`) {
      if(options.method==='PATCH')current={...current,...JSON.parse(options.body),revision:current.revision+1};
      return response(current);
    }
    throw Error(`Unexpected native request: ${url}`);
  };
  return {fetcher,calls,saved:()=>current};
}
test('duration readiness locks generation, ignores stale parents and preserves an incompatible draft',async()=>{
  const late=deferred();
  const placement='1'.repeat(32);
  const saved={project_id:C,title:'Saved',revision:1,placements:[{placement_id:placement,take_id:B}],
    selected_placement_id:placement,drafts:{[placement]:{prompt:'Saved direction',seed:'7',raw_frames:158}}};
  const backend=nativeBackend({saved,extra:async url=>{
    if(url===`/api/continuity/takes/${A}/readiness`)return late.promise;
    if(url===`/api/continuity/takes/${B}/readiness`)return response({verified:true,extend:true,
      duration_options:[{raw_frames:175,seconds:140/24},{raw_frames:277,seconds:242/24}]});
  }});
  const app=await environment(backend.fetcher,'',{'opengenjutsu.sequence.project':C});
  await app.entry('continuity-studio.js');await flush();const e=app.elements;
  assert.equal(e.get('forward-length').value,'158','never silently change a saved incompatible length');
  assert.equal(e.get('forward-submit').disabled,true);
  assert.match(e.get('forward-duration-hint').textContent,/choose/i);
  await e.get('forward-form').fire('submit');await flush();
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')),false);
  e.get('forward-length').value='175';await e.get('forward-length').fire('input');
  assert.equal(e.get('forward-submit').disabled,false);
  assert.equal(backend.saved().drafts[placement].raw_frames,158,'draft debounce not yet flushed');
  await e.get('native-takes').children[0].children[0].click();await flush();
  assert.equal(e.get('forward-length').disabled,true,'no static choices while checking');
  await e.get('board-track').children[1].children[0].click();await flush();
  assert.equal(e.get('forward-length').value,'175');
  late.resolve(response({verified:true,extend:true,duration_options:[{raw_frames:158,seconds:5.125}]}));await flush();
  assert.equal(e.get('forward-length').value,'175','late response from A cannot rewrite B');
  assert.equal(e.get('forward-prompt').value,'Saved direction');
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')),false);
});

test('duration picker preserves non-preset saved choices and fails closed on malformed readiness',async()=>{
  const app=await environment(()=>{throw Error('Picker must not fetch');});
  const {createDurationPicker}=await app.entry('continuity-duration.js');
  const e=app.elements, select=e.get('forward-length');
  const picker=createDurationPicker(select,e.get('forward-duration-hint'));
  const options=[{raw_frames:175,seconds:140/24},{raw_frames:243,seconds:208/24},{raw_frames:277,seconds:242/24}];
  picker.reset(243);picker.ready({extend:true,duration_options:options});
  assert.equal(select.value,'243');assert.equal(picker.valid(),true);
  assert.ok(select.children.some(o=>o.value==='243'));
  picker.setLocked(true);assert.equal(select.disabled,true);
  picker.setLocked(false);assert.equal(select.disabled,false);
  picker.reset();picker.ready({extend:true,duration_options:options});
  assert.equal(select.value,'277','only a new draft gets the nearest default');
  picker.ready({extend:true,duration_options:[{raw_frames:158,seconds:'5'}]});
  assert.equal(select.disabled,true);assert.equal(picker.valid(),false);
});

test('readiness failure never leaves a previous duration enabled',async()=>{
  const backend=nativeBackend({extra:async url=>url.endsWith('/readiness')?new Response('{}',{status:503}):null});
  const app=await environment(backend.fetcher);await app.entry('continuity-studio.js');await flush();
  const e=app.elements;await e.get('native-takes').children[0].children[1].click();await flush();
  assert.equal(e.get('forward-length').disabled,true);
  assert.equal(e.get('forward-submit').disabled,true);
  assert.match(e.get('forward-duration-hint').textContent,/unavailable/i);
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')),false);
});

test('library preview exposes direction and references; placement is explicit and never generates',async()=>{
  const backend=nativeBackend(),app=await environment(backend.fetcher);
  await app.entry('continuity-studio.js');await flush();
  const e=app.elements;
  await e.get('native-takes').children[0].children[0].click();await flush();
  assert.equal(e.get('native-library').hidden,false,'preview must not dismiss the take library');
  assert.equal(e.get('forward-form').hidden,false,'setup may not disappear behind placement requirement');
  assert.equal(e.get('forward-references').hidden,false);
  assert.equal(e.get('forward-reference-list').children.length,1);
  assert.equal(e.get('forward-open').disabled,false);
  assert.equal(e.get('forward-submit').disabled,true,'library preview is not an implicit placement');
  e.get('forward-prompt').value='Continue the shot';
  e.get('forward-seed').value='18446744073709551615';
  await e.get('forward-open').click();await flush();
  assert.equal(e.get('forward-form').hidden,false);
  assert.equal(e.get('forward-submit').disabled,false);
  const saved=backend.saved();assert.equal(saved.placements.length,1);
  assert.equal(saved.drafts[saved.selected_placement_id].prompt,'Continue the shot');
  assert.equal(saved.drafts[saved.selected_placement_id].seed,'18446744073709551615');
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')),false);
});
test('library remains usable for multiple placements, returning to drafts and reopening a saved sequence',async()=>{
  const backend=nativeBackend(),app=await environment(backend.fetcher);
  await app.entry('continuity-studio.js');await flush();const e=app.elements;
  await e.get('native-takes').children[0].children[1].click();await flush();
  assert.equal(e.get('native-library').hidden,false,'adding one must leave other takes available');
  e.get('forward-prompt').value='Keep draft A';await e.get('forward-prompt').fire('input');
  e.get('forward-seed').value='18446744073709551615';await e.get('forward-seed').fire('input');
  await e.get('native-takes').children[1].children[1].click();await flush();
  assert.equal(e.get('native-library').hidden,false);
  assert.equal(e.get('board-track').children.length,5,'two placements and three creation positions');
  await e.get('board-track').children[1].children[0].click();await flush();
  assert.equal(e.get('forward-prompt').value,'Keep draft A');
  assert.equal(e.get('forward-seed').value,'18446744073709551615');
  await e.get('native-library-close').click();
  assert.equal(e.get('native-library').hidden,true);
  assert.equal(e.get('native-library-toggle').getAttribute('aria-expanded'),'false');
  await e.get('native-rail-add').click();
  assert.equal(e.get('native-library').hidden,false,'rail add works with a selected take too');
  assert.equal(e.get('native-library-toggle').getAttribute('aria-expanded'),'true');
  await e.get('native-library').fire('keydown',{key:'Escape'});
  assert.equal(e.get('native-library').hidden,true);
  await e.get('board-track').children[3].children[1].children[2].click();await flush();
  assert.equal(e.get('board-track').children.length,3,'removal only unplaces the take');
  assert.equal(e.get('native-takes').children.length,2,'neither original was removed');
  await e.get('native-rail-add').click();
  await e.get('native-takes').children[1].children[1].click();await flush();
  await e.get('board-track').children[1].children[0].click();await flush();
  assert.equal(e.get('forward-prompt').value,'Keep draft A');
  // Force and wait for the real module's debounced workspace PATCH, not a fixture save.
  await new Promise(r=>setTimeout(r,400));await flush();
  const saved=backend.saved();assert.equal(saved.placements.length,2);
  const reopened=await environment(backend.fetcher,'',{'opengenjutsu.sequence.project':C});
  await reopened.entry('continuity-studio.js');await flush();
  assert.equal(reopened.elements.get('native-library').hidden,false,'saved selection must not hide the library on entry');
  assert.equal(reopened.elements.get('forward-prompt').value,'Keep draft A');
  assert.equal(reopened.elements.get('board-track').children.length,5);
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')),false);
});

test('reloaded lost-response receipt reconnects by request without hiding setup or issuing POST',async()=>{
  const placement='1'.repeat(32),request='2'.repeat(32),attempt='3'.repeat(32);
  const saved={project_id:C,title:'Saved',revision:1,placements:[{placement_id:placement,take_id:A}],
    selected_placement_id:placement,drafts:{[placement]:{prompt:'My saved direction',seed:'7',raw_frames:158}}};
  const receipt={version:2,project_id:C,after:placement,take_id:A,request_id:request,
    attempt_id:null,status:'unknown',body:'literal saved JSON'};
  const backend=nativeBackend({saved,extra:async url=>url.endsWith(`/attempts/by-request/${request}`)
    ?response({attempt_id:attempt,take_id:A,status:'failed',error:'Transport failed',candidates:[]}):null});
  const app=await environment(backend.fetcher,'',{'opengenjutsu.sequence.project':C,
    'opengenjutsu.sequence.pending-generation':JSON.stringify(receipt)});
  await app.entry('continuity-studio.js');await flush();
  assert.equal(app.elements.get('forward-form').hidden,false);
  assert.equal(app.elements.get('forward-prompt').value,'My saved direction');
  assert.equal(app.elements.get('forward-submit').disabled,false,'terminal recovery must unlock explicit generation');
  assert.equal(app.elements.get('attempt-recovery').hidden,false);
  assert.equal(app.elements.get('attempt-dismiss').hidden,false);
  assert.equal(backend.calls.some(c=>c.method==='POST'),false);
  assert.equal(JSON.parse(app.storage.get('opengenjutsu.sequence.pending-generation')).attempt_id,attempt);
});
test('late references from a previous preview never overwrite the selected take setup',async()=>{
  const first=deferred();
  const backend=nativeBackend({extra:async url=>url===`/api/continuity/takes/${A}/references`?first.promise:null});
  const app=await environment(backend.fetcher);await app.entry('continuity-studio.js');await flush();
  const e=app.elements;
  await e.get('native-takes').children[0].children[0].click();await flush();
  await e.get('native-takes').children[1].children[0].click();await flush();
  first.resolve(response({references:[{index:9}]}));await flush();
  const image=e.get('forward-reference-list').children[0].children[0];
  assert.equal(image.src,`/api/continuity/takes/${B}/references/1`);
});

test('candidate comparison is explicit, read-only, stable through polls and cleaned on transition',async()=>{
  const app=await environment(()=>{throw Error('Comparison must not fetch or write');});
  const {mountCandidateComparison,candidateSeed}=await app.entry('candidate-comparison.js');
  const player=new Element(),panel=new Element(),label=new Element(),message=new Element(),close=new Element();
  const comparison=mountCandidateComparison({player,panel,label,message,close});
  const view={attempt_id:A,status:'running',candidates:[{status:'done',take_id:B,seed:7},{status:'pending',seed:8}]};
  const frozen={project_id:C,after:A,take_id:A,body:'{"seeds":[18446744073709551615,0]}'};
  const original=JSON.stringify({view,frozen});
  comparison.update(view,frozen);
  assert.ok(!player.src,'no media source until explicit Preview');
  assert.equal(candidateSeed(view.candidates[0],0,frozen),'18446744073709551615');
  assert.equal(candidateSeed({seed:18446744073709551615},0,{}),'unavailable (exact value not provided)');
  assert.equal(candidateSeed({seed:'18446744073709551615'},0,{}),'18446744073709551615');
  assert.equal(candidateSeed({seed:7},0,{}),'7');
  comparison.preview(1);assert.ok(!player.src,'unfinished candidates have no preview');
  comparison.preview(0);
  assert.equal(player.src,`/api/continuity/takes/${B}/media`);
  assert.equal(player.preload,'none');assert.equal(player.controls,true);assert.equal(player.playsInline,true);
  assert.equal(player.paused,true);assert.equal(panel.hidden,false);
  player.currentTime=3;await player.play();const loads=player.loadCount;
  comparison.update(structuredClone(view),structuredClone(frozen));
  assert.equal(player.currentTime,3);assert.equal(player.paused,false,'poll must not reset playback');
  assert.equal(player.loadCount,loads,'poll must not reload the media element');
  comparison.update({...view,candidates:[...view.candidates,{status:'done',take_id:C,seed:9}]},frozen);
  comparison.preview(2);assert.equal(player.src,`/api/continuity/takes/${C}/media`);
  assert.equal(player.paused,true,'switching candidate never autoplays');
  comparison.preview(0);
  assert.equal(JSON.stringify({view,frozen}),original,'preview cannot mutate attempt or anchor');
  await player.fire('error');assert.match(message.textContent,/unavailable/);
  comparison.update({...view,status:'done'},frozen);assert.match(message.textContent,/unavailable/);
  await close.click();assert.equal(player.src,'');assert.equal(panel.hidden,true);assert.equal(player.paused,true);
  comparison.preview(0);comparison.update({...view,attempt_id:C},frozen);
  assert.equal(player.src,'');assert.equal(panel.hidden,true,'different attempt releases old media');
  comparison.update({...view,candidates:[{status:'done',take_id:'../../etc',seed:1}]},frozen);
  comparison.preview(0);assert.equal(player.src,'');
});

test('recovered candidates preview without changing draft or sequence; Keep uses frozen anchor only',async()=>{
  const placement='1'.repeat(32),attempt='3'.repeat(32);
  const saved={project_id:C,title:'Saved',revision:1,placements:[{placement_id:placement,take_id:A}],
    selected_placement_id:placement,drafts:{[placement]:{prompt:'Original draft',seed:'7',raw_frames:158}}};
  const view={attempt_id:attempt,take_id:A,status:'failed',error:'One candidate failed',
    candidates:[{status:'done',take_id:B,seed:7},{status:'failed',take_id:null,seed:8,error:'Test failure'}]};
  const receipt={version:2,project_id:C,after:placement,take_id:A,request_id:'2'.repeat(32),
    attempt_id:attempt,status:'unknown',body:'{"seeds":[18446744073709551615,0]}'};
  const backend=nativeBackend({saved,extra:async url=>url===`/api/continuity/attempts/${attempt}`?response(view):null});
  const app=await environment(backend.fetcher,'',{'opengenjutsu.sequence.project':C,
    'opengenjutsu.sequence.pending-generation':JSON.stringify(receipt)});
  await app.entry('continuity-studio.js');await flush();const e=app.elements;
  const find=(row,text)=>row.children.find(child=>child.textContent===text);
  const row=e.get('candidate-list').children[0];
  assert.equal(e.get('forward-variants').value,'2','reconnect must show the saved hunt count, not a default one-take form');
  assert.ok(row.children.some(child=>child.textContent.includes('18446744073709551615')));
  const before=JSON.stringify(backend.saved()),calls=backend.calls.length;
  await find(row,'Preview video / audio').click();await flush();
  assert.equal(e.get('candidate-video').src,`/api/continuity/takes/${B}/media`);
  assert.equal(JSON.stringify(backend.saved()),before);assert.equal(backend.calls.length,calls);
  assert.equal(e.get('forward-prompt').value,'Original draft');assert.equal(e.get('native-library').hidden,false);
  // Selection can change independently; Keep must still insert after the frozen placement.
  await e.get('native-takes').children[1].children[1].click();await flush();
  e.get('forward-variants').value='2';
  await find(row,'Keep').click();await flush();
  assert.equal(e.get('forward-form').hidden,false,'Keep must expose the chosen state as the next creative starting point');
  assert.equal(e.get('forward-variants').value,'1','a new continuation must not silently repeat the previous hunt');
  assert.deepEqual(backend.saved().placements.map(p=>p.take_id),[A,B,B]);
  assert.equal(e.get('candidate-video').src,'');assert.equal(e.get('candidate-tray').hidden,true);
  assert.equal(e.get('native-takes').children.length,2,'alternatives stay in library');
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')&&c.method==='POST'),false);
});

test('Keep is gated until terminal and refuses a different frozen project without writes',async()=>{
  for(const status of ['running','failed']) {
    const placement='1'.repeat(32),attempt='3'.repeat(32);
    const saved={project_id:C,title:'Saved',revision:1,placements:[{placement_id:placement,take_id:A}],
      selected_placement_id:placement,drafts:{[placement]:{prompt:'Keep draft',seed:'7',raw_frames:158}}};
    const receipt={version:2,project_id:B,after:placement,take_id:A,request_id:'2'.repeat(32),
      attempt_id:attempt,status:'unknown',body:'{"seeds":[7]}'};
    const view={attempt_id:attempt,take_id:A,status,error:null,candidates:[{status:'done',take_id:B,seed:7}]};
    const backend=nativeBackend({saved,extra:async url=>url===`/api/continuity/attempts/${attempt}`?response(view):null});
    const app=await environment(backend.fetcher,'',{'opengenjutsu.sequence.project':C,
      'opengenjutsu.sequence.pending-generation':JSON.stringify(receipt)});
    await app.entry('continuity-studio.js');await flush();const e=app.elements;
    const row=e.get('candidate-list').children[0],keep=row.children.find(c=>c.textContent==='Keep');
    assert.equal(keep.disabled,status==='running');
    const before=JSON.stringify(backend.saved()),calls=backend.calls.length;
    await row.children.find(c=>c.textContent==='Preview video / audio').click();
    if(status==='failed') {
      await keep.click();
      assert.match(e.get('forward-state').textContent,/original saved sequence/);
      assert.equal(e.get('candidate-tray').hidden,false);
    }
    assert.equal(JSON.stringify(backend.saved()),before);assert.equal(backend.calls.length,calls);
    for(const dispose of app.events.pagehide||[])dispose();
    assert.equal(e.get('candidate-video').src,'','pagehide releases comparison media');
  }
});

// Shipped ES modules run in isolated DOMs. Fixtures below are unit-test responses,
// not evidence of browser layout, valid decoded video, OS sharing or backend writes.
import test from 'node:test';
import {readMarkup} from './ui-markup.mjs';
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
async function environment(fetcher,search='',initialStorage={},page='timeline.html',libraryJobs=[]) {
  const markup=readMarkup(page);
  const elements=new Map([...markup.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)].map(([tag,id])=>{
    const element=new Element();element.hidden=/\bhidden(?:\s|>|=)/.test(tag);return [id,element];
  }));
  const notices=[],events={},navigation=[],historyURLs=[],storage=new Map(Object.entries(initialStorage));const location={search,href:'http://test.invalid/'+(page==='assembly.html'?'assembly':'timeline'),assign:url=>navigation.push(url)};
  const document={getElementById:id=>elements.get(id),createElement:()=>new Element(),
    querySelectorAll:selector=>selector==='video'?['native-video','candidate-video','timeline-video','export-video'].map(id=>elements.get(id)).filter(Boolean):[]};
  const context=vm.createContext({document,location,console,URLSearchParams,URL,Response,File,
    Blob,FormData,AbortSignal,queueMicrotask,fetch:async(url,options)=>url==='/api/timeline/library'?response({jobs:libraryJobs}):fetcher(url,options),setTimeout,clearTimeout,structuredClone,
    crypto:{randomUUID,getRandomValues:a=>webcrypto.getRandomValues(a)},
    Option:class extends Element{constructor(text,value){super();this.textContent=text;this.value=value;}},
    navigator:{share:async()=>{},canShare:()=>true},
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    history:{replaceState:(_,__,url)=>{historyURLs.push(url);location.href=new URL(url,'http://test.invalid').href;location.search=new URL(url,'http://test.invalid').search;}},
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
  return {elements,notices,entry,storage,events,navigation,historyURLs,context};
}

test('project membership remains visible immediately after removing a saved placement',async()=>{
  const saved={project_id:C,title:'Scoped project',revision:0,placements:[],selected_placement_id:null,drafts:{}};
  const backend=nativeBackend({saved,extra:async url=>url.endsWith('/assets')?response({project_id:C,assets:{takes:[],jobs:[]}}):null});
  const app=await environment(backend.fetcher,`?project_id=${C}`);
  app.context.window.OpenGenjutsuProject={ready:Promise.resolve()};
  const {mountSequence}=await app.entry('sequence-workspace.js');
  const seq=mountSequence({onSelect(){},onPreview(){},onCompose(){},onError:assert.fail});
  await seq.init([nativeEntry(A)]);seq.place(A);await seq.flush();
  await app.elements.get('board-track').children[1].children[1].children[2].click();await seq.flush();
  assert.equal(seq.state().placements.length,0);
  assert.equal(app.elements.get('native-takes').children[0].dataset.takeId,A,'removing a placement must not hide the retained project asset');
});

test('shared rename updates the same native revision without losing exact drafts or reverting the name',async()=>{
  const p='1'.repeat(32),saved={project_id:C,title:'Before',revision:4,
    placements:[{placement_id:p,take_id:A}],selected_placement_id:p,
    drafts:{[p]:{prompt:'Keep exact direction',seed:'18446744073709551615',raw_frames:158}}};
  const backend=nativeBackend({saved,extra:async url=>url.endsWith('/assets')
    ?response({project_id:C,assets:{takes:[A],jobs:[]}}):null}),app=await environment(backend.fetcher,`?project_id=${C}`);
  const scope={ready:Promise.resolve()};app.context.window.OpenGenjutsuProject=scope;
  const {mountSequence,takeLabel}=await app.entry('sequence-workspace.js');
  const seq=mountSequence({onSelect(){},onPreview(){},onCompose(){},onError:assert.fail});
  await seq.init([nativeEntry(A)]);
  seq.setDraft({prompt:'Before rename'});await scope.beforeNavigate();
  assert.equal(backend.saved().drafts[p].prompt,'Before rename');
  await scope.onRenamed({project_id:C,title:'Named in shared bar',revision:backend.saved().revision});
  seq.setDraft({prompt:'After rename'});await seq.flush();
  assert.equal(backend.saved().title,'Named in shared bar');
  assert.equal(backend.saved().drafts[p].seed,'18446744073709551615');
  assert.equal(backend.saved().placements[0].take_id,A);
  assert.match(takeLabel(nativeEntry(A)),/^Take · /);
  assert.ok(!takeLabel(nativeEntry(A)).includes(A.slice(0,8)));
  app.elements.get('native-search').value=A;await app.elements.get('native-search').fire('input');
  assert.equal(app.elements.get('native-takes').children[0].dataset.takeId,A,'full ID remains searchable');
});

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

test('New take uses the shared composer, exact seeds, root recovery and frozen empty position',async()=>{
  const D='d'.repeat(32),E='e'.repeat(32),R='f'.repeat(32);let generated=false,body=null;
  const saved={project_id:C,title:'Root',revision:1,placements:[],selected_placement_id:null,drafts:{}};
  const view={attempt_id:R,take_id:null,mode:'root',status:'done',error:null,
    candidates:[{seed:'18446744073709551615',status:'done',take_id:D,error:null},
      {seed:'0',status:'done',take_id:E,error:null}]};
  const backend=nativeBackend({saved,extra:async(url,options)=>{
    if(url.startsWith('/api/continuity/composer-readiness'))return response({available:true,
      duration_options:[{raw_frames:124,seconds:124/24},{raw_frames:243,seconds:243/24}]});
    if(url==='/api/continuity/root-references')return response({reference_id:A});
    if(url==='/api/continuity/roots/attempts'){body=options.body;generated=true;return response(view);}
  }});
  const app=await environment((url,options={})=>url==='/api/continuity/takes'&&generated
    ?Promise.resolve(response({takes:[nativeEntry(D),nativeEntry(E),nativeEntry(A),nativeEntry(B)]}))
    :backend.fetcher(url,options),`?character_id=${A}`,{'opengenjutsu.sequence.project':C});
  await app.entry('continuity-studio.js');await flush();const e=app.elements;
  await e.get('board-track').children[0].children[0].click();await flush();
  assert.equal(e.get('forward-form').hidden,false);
  assert.equal(e.get('forward-submit').disabled,true,'root needs explicit reference');
  assert.equal(generated,false,'opening a slot never submits');
  assert.equal(e.get('position-character').hidden,true);
  await e.get('native-character-image').fire('load');
  assert.equal(e.get('position-character').hidden,false,'late character handoff must remain usable in an open root draft');
  e.get('forward-prompt').value='A new shot';await e.get('forward-prompt').fire('input');
  e.get('forward-seed').value='18446744073709551615';await e.get('forward-seed').fire('input');
  e.get('forward-variants').value='2';await e.get('forward-variants').fire('input');
  e.get('forward-reference-input').files=[new File(['synthetic image'],'synthetic.png',{type:'image/png'})];
  await e.get('forward-reference-input').fire('change');await flush();
  assert.equal(e.get('forward-submit').disabled,false);
  await e.get('forward-form').fire('submit');await flush();
  assert.ok(body.includes('"seeds":[18446744073709551615,0]'));
  assert.equal(JSON.parse(body).reference_ids[0],A);
  assert.equal(JSON.parse(body).width,1024);
  const receipt=JSON.parse(app.storage.get('opengenjutsu.sequence.pending-generation'));
  assert.equal(receipt.take_id,null);assert.equal(receipt.mode,'root');assert.equal(receipt.position.left,null);
  const keep=e.get('candidate-list').children[0].children.find(child=>child.textContent==='Keep');
  await keep.click();await flush();
  assert.equal(backend.saved().placements.length,1);assert.equal(backend.saved().placements[0].take_id,D);
  assert.equal(e.get('forward-variants').value,'1');assert.equal(e.get('forward-form').hidden,false);
});

test('native seeking/play cannot replay trimmed-away prefix; sequence still advances',async()=>{
  const app=await environment(()=>{throw Error('No network in player');},'',{},'assembly.html');
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
  },`?project_id=${A}`,{},'assembly.html');
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
  assert.equal(e.get('native-rail-add').getAttribute('aria-expanded'),'false');
  await e.get('native-rail-add').click();
  assert.equal(e.get('native-library').hidden,false,'rail add works with a selected take too');
  assert.equal(e.get('native-rail-add').getAttribute('aria-expanded'),'true');
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
  let returned=0;comparison.preview(0,{returnTo:{focus(){returned++;}}});
  await close.click();assert.equal(returned,1);assert.equal(player.src,'');assert.equal(panel.hidden,true);assert.equal(player.paused,true);
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


test('project context parser is strict, pure and keeps distinct literal IDs',async()=>{
  const app=await environment(()=>{throw Error('Context parsing must not fetch');});
  const {parseProjectContext,workspaceLink}=await app.entry('project-context.js');
  const before=JSON.stringify([...app.storage]);
  const context=parseProjectContext(`?project_id=${A}&job_id=${B}&character_id=${C}`);
  assert.equal(context.project_id,A);assert.equal(context.job_id,B);assert.equal(context.character_id,C);
  for(const key of ['project_id','job_id','character_id'])for(const invalid of ['',A.toUpperCase(),'../../bad',A+'0'])
    assert.throws(()=>parseProjectContext(`?${key}=${invalid}`),/workspace link is invalid/i);
  for(const key of ['project_id','job_id','character_id'])
    assert.throws(()=>parseProjectContext(`?${key}=${A}&${key}=${A}`),/workspace link is invalid/i);
  const link=workspaceLink('/timeline',{job_id:B},`?project_id=${A}&character_id=${C}`);
  const params=new URL(link,'http://test.invalid').searchParams;
  assert.equal(params.get('project_id'),A);assert.equal(params.get('job_id'),B);assert.equal(params.has('character_id'),false);
  assert.throws(()=>workspaceLink('https://elsewhere.invalid/',{},''),/workspace destination/i);
  assert.throws(()=>workspaceLink('/timeline',{job_id:'bad'},''),/workspace link is invalid/i);
  assert.equal(JSON.stringify([...app.storage]),before);
});


test('explicit project wins browser memory without writing or losing saved drafts',async()=>{
  const saved={project_id:C,title:'Remembered',revision:1,placements:[],selected_placement_id:null,drafts:{}};
  const explicit={...saved,project_id:B,title:'Linked project',drafts:{[A]:{prompt:'Unchanged',seed:'7'}}};
  const backend=nativeBackend({saved,extra:async url=>url===`/api/timeline/projects/${B}/native-workspace`?response(explicit):null});
  const app=await environment(backend.fetcher,`?project_id=${B}`,{'opengenjutsu.sequence.project':C});
  const {mountSequence}=await app.entry('sequence-workspace.js');
  const sequence=mountSequence({onSelect(){},onPreview(){},onCompose(){},onError:assert.fail});
  await sequence.init([nativeEntry(A)]);
  assert.equal(sequence.state().project_id,B);assert.equal(sequence.state().drafts[A].prompt,'Unchanged');
  assert.equal(app.storage.get('opengenjutsu.sequence.project'),B);
  assert.equal(backend.calls.some(c=>c.url.includes(`${C}/native-workspace`)),false);
  assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
});

test('missing or malformed explicit project refuses fallback and accidental edits',async()=>{
  for(const search of [`?project_id=${B}`,`?project_id=${A}&project_id=${B}`,'?project_id=../bad']){
    const messages=[],backend=nativeBackend({saved:{project_id:C,title:'Remembered',revision:1,
      placements:[],selected_placement_id:null,drafts:{}},extra:async url=>
      url===`/api/timeline/projects/${B}/native-workspace`?new Response('{}',{status:404}):null});
    const app=await environment(backend.fetcher,search,{'opengenjutsu.sequence.project':C});
    const {mountSequence}=await app.entry('sequence-workspace.js');
    const sequence=mountSequence({onSelect(){},onPreview(){},onCompose(){},onError:m=>messages.push(m)});
    try{await sequence.init([nativeEntry(A)]);}catch(error){messages.push(error.message);}
    assert.equal(sequence.state().project_id,null);assert.equal(sequence.editable(),false);
    assert.ok(messages.length);assert.equal(backend.calls.some(c=>c.url.includes(`${C}/native-workspace`)),false);
    sequence.place(A);await assert.rejects(()=>sequence.flush(),/linked project|workspace link|choose a project/i);
    assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
    assert.equal(app.storage.get('opengenjutsu.sequence.project'),C);
  }
});

test('a mixed old project opens native placements without an archived editor or conversion',async()=>{
  const saved={project_id:C,title:'Old cut',revision:3,placements:[],selected_placement_id:null,drafts:{}};
  const backend=nativeBackend({saved,extra:async url=>url==='/api/timeline/projects'
    ?response({projects:[{...saved,workspace_kind:'legacy',legacy_clip_count:2,native_placement_count:0}]}):null});
  const app=await environment(backend.fetcher,`?project_id=${C}`),e=app.elements;
  const {mountSequence}=await app.entry('sequence-workspace.js');
  const sequence=mountSequence({onSelect(){},onPreview(){},onCompose(){},onError:assert.fail});
  await sequence.init([nativeEntry(A)]);
  assert.equal(e.has('native-project-picker'),false);
  assert.equal(e.has('native-project-kind'),false);
  assert.equal(e.has('native-legacy-open'),false);
  assert.equal(e.has('supporting-tools'),false);
  assert.deepEqual(app.navigation,[]);
  assert.equal(backend.saved().revision,3);assert.equal(sequence.state().placements.length,0);
  assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
});


const sourceEntry=(id,job)=>{const entry=nativeEntry(id);entry.take.origin={source_job:job,operator_label:'native-swap'};return entry;};
test('saved-cut navigation never creates a project or imports URL source assets',async()=>{
  const calls=[];const app=await environment(async(url,options={})=>{
    calls.push({url,method:options.method||'GET'});
    if(url==='/api/jobs')return response([]);
    if(url==='/api/timeline/projects')return response({projects:[]});
    throw Error(`Unexpected mutation/read ${url}`);
  },`?job_id=${B}&character_id=${C}`,{},'assembly.html');
  await app.entry('timeline.js');await flush();
  assert.ok(calls.length>0);assert.ok(calls.every(c=>c.method==='GET'));
  assert.equal(app.elements.has('native-video'),false);
  assert.equal(app.elements.get('timeline-error').hidden,true);
  assert.ok(app.historyURLs.every(url=>url.startsWith('/assembly')));
});

test('failed native save blocks shared project navigation and preserves recovery',async()=>{
  const saved={project_id:C,title:'Saved',revision:3,placements:[],selected_placement_id:null,drafts:{}};
  const backend=nativeBackend({saved,extra:async(url,options)=>{
    if(options.method==='PATCH')return new Response(JSON.stringify({detail:'Reload required'}),{status:409});
    if(url.endsWith('/assets'))return response({project_id:C,assets:{takes:[A],jobs:[]}});
  }});
  const app=await environment(backend.fetcher,`?project_id=${C}`),errors=[];
  const scope={ready:Promise.resolve()};app.context.window.OpenGenjutsuProject=scope;
  const {mountSequence}=await app.entry('sequence-workspace.js');
  const sequence=mountSequence({onSelect(){},onPreview(){},onCompose(){},onError:message=>errors.push(message)});
  await sequence.init([nativeEntry(A)]);sequence.place(A);
  await assert.rejects(scope.beforeNavigate(),/Reload required/);
  assert.equal(app.navigation.length,0);assert.ok(errors.length>0);
  assert.equal(sequence.state().placements[0].take_id,A);assert.ok(app.storage.get('opengenjutsu.sequence.recovery'));
});

test('position reference failure preserves ready durations and draft without generation',async()=>{
  const app=await environment(()=>{throw Error('No write allowed');});
  const {mountPositionGeneration}=await app.entry('position-generation.js');
  const {createDurationPicker}=await app.entry('continuity-duration.js');
  const e=app.elements,draft={prompt:'Keep draft',seed:'7',raw_frames:158,count:1,reference_ids:[]};
  e.get('native-library').hidden=false;
  const picker=createDurationPicker(e.get('forward-length'),e.get('forward-duration-hint'));
  const controller=mountPositionGeneration({sequence:{state:()=>({placements:[{placement_id:A,take_id:B}]}),
    setPositionDraft(){assert.fail('Read must not save');}},byId:id=>e.get(id),duration:picker,
    onUpdate(){},onMessage(){},getJSON:async url=>{
      if(url.includes('composer-readiness'))return {available:true,reason_code:null,duration_options:[{raw_frames:158,seconds:5.125}]};
      throw Error('/private/SECRET reference failed');
    }});
  await controller.open({mode:'forward',left:A,right:null},draft);
  assert.equal(picker.valid(),true);assert.equal(e.get('forward-length').disabled,false);
  assert.equal(controller.valid(),false);
  assert.match(e.get('native-readiness').textContent,/references.*could not be loaded/i);
  assert.equal(e.get('forward-prompt').value,'Keep draft');
  assert.equal(e.get('native-library').hidden,false);
  assert.doesNotMatch(e.get('native-readiness').textContent,/SECRET/);
});

test('explicit custom reference recovers from inherited reference failure without changing durations',async()=>{
  const app=await environment(async url=>{assert.equal(url,'/api/continuity/root-references');return response({reference_id:C});});
  const {mountPositionGeneration}=await app.entry('position-generation.js');
  const {createDurationPicker}=await app.entry('continuity-duration.js');
  const e=app.elements;let draft={prompt:'Preserve direction',seed:'7',raw_frames:158,count:1,reference_ids:[],reference_mode:'inherit'};
  const picker=createDurationPicker(e.get('forward-length'),e.get('forward-duration-hint'));
  const controller=mountPositionGeneration({sequence:{state:()=>({placements:[{placement_id:A,take_id:B}]}),
    setPositionDraft:changes=>{draft={...draft,...changes};},positionDraft:()=>structuredClone(draft)},
    byId:id=>e.get(id),duration:picker,onUpdate(){},onMessage(){},getJSON:async url=>{
      if(url.includes('composer-readiness'))return {available:true,reason_code:null,duration_options:[{raw_frames:158,seconds:5.125}]};
      throw Error('Synthetic reference failure');
    }});
  await controller.open({mode:'forward',left:A,right:null},draft);
  assert.equal(controller.valid(),false);assert.equal(picker.valid(),true);
  await controller.add(new File(['synthetic image upload'],'test.png',{type:'image/png'}));
  assert.equal(controller.valid(),true);assert.equal(picker.valid(),true);
  assert.equal(draft.prompt,'Preserve direction');assert.equal(draft.seed,'7');
  assert.equal(e.get('native-readiness').textContent,'Saved timing checked.');
});

test('duration refusal explains operation instead of requesting the same incompatible take again',async()=>{
  const app=await environment(()=>assert.fail('Picker does not fetch'));
  const {createDurationPicker}=await app.entry('continuity-duration.js');
  const e=app.elements,picker=createDurationPicker(e.get('forward-length'),e.get('forward-duration-hint'));
  picker.ready({available:false,mode:'prepend',reason_code:'unaligned_start',duration_options:[]});
  assert.match(e.get('forward-duration-hint').textContent,/prepend/i);
  assert.doesNotMatch(e.get('forward-duration-hint').textContent,/refresh/i);
  picker.unavailable();assert.match(e.get('forward-duration-hint').textContent,/request|check/i);
});
test('Swap native handoff previews its real family without adding or editing the sequence',async()=>{
  const placement='1'.repeat(32),saved={project_id:C,title:'Existing',revision:7,
    placements:[{placement_id:placement,take_id:B}],selected_placement_id:placement,
    drafts:{[placement]:{prompt:'Keep my direction',seed:'18446744073709551615',raw_frames:158}}};
  const backend=nativeBackend({saved}),before=JSON.stringify(saved);
  const app=await environment((url,options)=>url==='/api/continuity/takes'
    ?Promise.resolve(response({takes:[sourceEntry(A,B),nativeEntry(B)]})):backend.fetcher(url,options),`?job_id=${B}&project_id=${C}`);
  await app.entry('continuity-studio.js');await flush();const e=app.elements;
  assert.equal(e.get('native-video').src,`/api/continuity/takes/${A}/media`);
  assert.equal(e.get('native-handoff').hidden,false);
  assert.equal(e.get('native-handoff-add').textContent,'Add this take');
  assert.equal(JSON.stringify(backend.saved()),before);assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
  await e.get('native-handoff-add').click();await flush();
  assert.deepEqual(backend.saved().placements.map(p=>p.take_id),[B,A]);
  assert.equal(backend.saved().drafts[placement].prompt,'Keep my direction');
  assert.equal(backend.calls.some(c=>c.url.endsWith('/attempts')),false);
});

test('ambiguous native source requires an explicit version choice and never picks newest',async()=>{
  const backend=nativeBackend(),app=await environment((url,options)=>url==='/api/continuity/takes'
    ?Promise.resolve(response({takes:[sourceEntry(A,C),sourceEntry(B,C)]})):backend.fetcher(url,options),`?job_id=${C}`);
  await app.entry('continuity-studio.js');await flush();const e=app.elements;
  assert.equal(e.get('native-video').src||'', '');assert.equal(e.get('native-handoff-choices').children.length,2);
  await e.get('native-handoff-choices').children[1].click();await flush();
  assert.equal(e.get('native-video').src,`/api/continuity/takes/${B}/media`);
  assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
});

test('completed video-only Swap opens real video with an honest native-state alternative',async()=>{
  const backend=nativeBackend({extra:async url=>url===`/api/jobs/${C}`
    ?response({id:C,status:'done',engine:'ltx25-ripple',result_url:`/api/jobs/${C}/result`}):null});
  const app=await environment(backend.fetcher,`?job_id=${C}`);await app.entry('continuity-studio.js');await flush();const e=app.elements;
  assert.equal(e.get('native-video').src,`/api/jobs/${C}/result`);
  assert.match(e.get('native-handoff-message').textContent,/video only/i);
  assert.equal(e.get('native-handoff-add').hidden,true);assert.equal(e.get('native-handoff-new').hidden,false);
  assert.equal(e.get('forward-submit').disabled,true);assert.equal(e.get('native-capsule-download').hidden,true);
  assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
});

test('missing and stale Swap replies cannot replace a newer explicit take preview',async()=>{
  const late=deferred(),placement='1'.repeat(32),saved={project_id:C,title:'Chosen later',revision:1,
    placements:[{placement_id:placement,take_id:A}],selected_placement_id:placement,drafts:{}};
  const backend=nativeBackend({saved,extra:async url=>url===`/api/jobs/${B}`?late.promise:null});
  const app=await environment(backend.fetcher,`?job_id=${B}`,{'opengenjutsu.sequence.project':C});await app.entry('continuity-studio.js');await flush();
  const e=app.elements;await e.get('native-takes').children[0].children[0].click();await flush();
  late.resolve(response({id:B,status:'done',engine:'ltx25-ripple',result_url:`/api/jobs/${B}/result`}));await flush();
  assert.equal(e.get('native-video').src,`/api/continuity/takes/${A}/media`);
  assert.equal(e.get('native-handoff').hidden,true);assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
  const missing=nativeBackend({extra:async url=>url===`/api/jobs/${C}`?new Response('{}',{status:404}):null});
  const other=await environment(missing.fetcher,`?job_id=${C}`);await other.entry('continuity-studio.js');await flush();
  assert.match(other.elements.get('native-error').textContent,/unavailable|not.*available/i);
  assert.equal(other.elements.get('native-video').src||'','');assert.equal(missing.calls.some(c=>c.method!=='GET'),false);
});


test('project navigation carries source IDs, follows deliberate switches and protects explicit links',async()=>{
  const app=await environment(()=>{throw Error('Navigation context never fetches');});
  const {bindProjectNavigation}=await app.entry('project-context.js');let search=`?project_id=${A}`;
  const character=new Element(),result=new Element(),explicit=new Element(),download=new Element(),navigation=new Element();
  navigation.setAttribute('href','/timeline');
  character.setAttribute('href',`/h3?character_id=${B}`);result.setAttribute('href',`/timeline?job_id=${C}`);
  explicit.setAttribute('href',`/timeline?project_id=${B}&job_id=${C}`);download.setAttribute('href',`/api/jobs/${C}/result`);
  const binding=bindProjectNavigation({getSearch:()=>search,root:{querySelectorAll:()=>[character,result,explicit,download,navigation]},observe:false});
  const params=el=>new URL(el.getAttribute('href'),'http://test.invalid').searchParams;
  assert.equal(params(character).get('project_id'),A);assert.equal(params(character).get('character_id'),B);
  assert.equal(params(result).get('job_id'),C);assert.equal(params(explicit).get('project_id'),B);
  search=`?project_id=${C}`;binding.refresh();
  assert.equal(params(character).get('project_id'),C);assert.equal(params(result).get('project_id'),C);
  assert.equal(params(explicit).get('project_id'),B,'an explicit frozen destination is not rebound');
  result.setAttribute('href',`/timeline?job_id=${A}`);binding.refresh();
  assert.equal(params(result).get('job_id'),A);assert.equal(params(result).get('project_id'),C);
  search=`?project_id=${C}&character_id=${B}`;binding.refresh();
  assert.equal(params(navigation).get('character_id'),B,'explicit working reference follows workspace navigation');
  assert.equal(params(result).has('character_id'),false,'a saved result must not consume a new reference');
  assert.equal(params(explicit).has('character_id'),false,'never leak a reference into a different project');
  search='';binding.refresh();assert.equal(params(character).has('project_id'),false);
  assert.equal(download.getAttribute('href'),`/api/jobs/${C}/result`);binding.dispose();
});


test('opening a project locks editing until its authoritative read finishes',async()=>{
  const late=deferred(),backend=nativeBackend({extra:async url=>url===`/api/timeline/projects/${B}/native-workspace`?late.promise:null});
  const app=await environment(backend.fetcher,`?project_id=${B}`),e=app.elements;
  const {mountSequence}=await app.entry('sequence-workspace.js'),errors=[];
  const sequence=mountSequence({onSelect(){},onPreview(){},onCompose(){},onError:m=>errors.push(m)});
  const opening=sequence.init([nativeEntry(A)]);await flush();
  assert.equal(sequence.editable(),false);assert.equal(e.get('native-rail-add').disabled,true);
  sequence.place(A);assert.equal(sequence.state().placements.length,0);
  late.resolve(response({project_id:B,title:'Server choice',revision:4,placements:[],selected_placement_id:null,drafts:{}}));await opening;
  assert.equal(sequence.editable(),true);assert.equal(e.get('native-rail-add').disabled,false);
  assert.equal(sequence.state().project_id,B);assert.equal(backend.calls.some(c=>c.method!=='GET'),false);
});


test('candidate inspection occupies the main stage and restores its source paused without writes',async()=>{
  const placement='1'.repeat(32),attempt='3'.repeat(32);
  const saved={project_id:C,title:'Comparison',revision:4,placements:[{placement_id:placement,take_id:A}],
    selected_placement_id:placement,drafts:{[placement]:{prompt:'Continue this exact state',seed:'18446744073709551615',raw_frames:158}}};
  const receipt={version:2,project_id:C,after:placement,take_id:A,request_id:'2'.repeat(32),
    attempt_id:attempt,status:'unknown',body:'{"seeds":[18446744073709551615]}'};
  const view={attempt_id:attempt,take_id:A,status:'done',candidates:[{status:'done',take_id:B,seed:7}]};
  const backend=nativeBackend({saved,extra:async url=>url===`/api/continuity/attempts/${attempt}`?response(view):null});
  const app=await environment(backend.fetcher,'',{'opengenjutsu.sequence.project':C,
    'opengenjutsu.sequence.pending-generation':JSON.stringify(receipt)});
  await app.entry('continuity-studio.js');await flush();const e=app.elements,source=e.get('native-video');
  assert.equal(e.get('attempt-recovery').hidden,true,'successful recovered results are not an incident panel');
  source.currentTime=1;await source.play();
  const original=JSON.stringify(backend.saved()),calls=backend.calls.length;
  await e.get('candidate-list').children[0].children.find(c=>c.textContent==='Preview video / audio').click();
  assert.equal(source.paused,true,'one active audio stream');
  assert.equal(e.get('native-preview-stage').hidden,true);assert.equal(e.get('native-capsule').hidden,true);
  assert.equal(e.get('candidate-preview').hidden,false);assert.match(e.get('candidate-preview-label').textContent,/18446744073709551615/);
  await e.get('candidate-video').play();assert.equal(source.paused,true);
  await e.get('candidate-preview-close').click();
  assert.equal(e.get('native-preview-stage').hidden,false);assert.equal(e.get('native-capsule').hidden,false);
  assert.equal(source.currentTime,1);assert.equal(source.paused,true,'Close never autoplays the source');
  assert.equal(e.get('candidate-video').paused,true);assert.equal(e.get('candidate-video').src,'');
  assert.equal(e.get('forward-prompt').value,'Continue this exact state');
  assert.equal(JSON.stringify(backend.saved()),original);assert.equal(backend.calls.length,calls);
});

test('completed Swaps are visible without automatic placement; explicit add and reload keep their type',async()=>{
  for(const engine of ['minimax-h3','ltx25-ripple']) {
    const saved={project_id:C,title:'Swap project',revision:0,placements:[],selected_placement_id:null,drafts:{}};
    const backend=nativeBackend({saved,extra:async url=>url.endsWith('/assets')?response({project_id:C,assets:{takes:[],jobs:[B]}}):null});
    const app=await environment(backend.fetcher,`?project_id=${C}`,{},'timeline.html',[{job_id:B,engine,status:'done',created:1}]);
    app.context.window.OpenGenjutsuProject={ready:Promise.resolve()};
    await app.entry('continuity-studio.js');await flush();const e=app.elements;
    assert.equal(backend.saved().placements.length,0,'filing is not a placement');
    const row=e.get('native-takes').children.find(r=>r.dataset.sourceKind==='swap');assert.ok(row);
    await row.children[0].click();await flush();
    assert.equal(e.get('native-video').src,`/api/jobs/${B}/result`);
    assert.equal(e.get('forward-form').hidden,true,'video-only preview never offers native generation');
    assert.equal(e.get('native-capsule-download').hidden,true);
    assert.equal(backend.calls.some(c=>c.method==='POST'),false);
    await row.children[1].click();await flush();
    const {mountSequence}=await app.entry('sequence-workspace.js');
    // Flush the actual page via its existing navigation guard.
    await app.context.window.OpenGenjutsuProject.beforeNavigate();
    assert.equal(backend.saved().placements.length,1);
    assert.equal(backend.saved().placements[0].source_kind,'swap');
    assert.equal(backend.calls.some(c=>c.method==='POST'),false,'placing never generates');
  }
});

test('video-only anchors refuse native timing before network calls; independent New take remains available',async()=>{
  const saved={project_id:C,title:'Video anchor',revision:0,placements:[{placement_id:A,take_id:B,source_kind:'swap'}],selected_placement_id:A,drafts:{}};
  const backend=nativeBackend({saved});const app=await environment(backend.fetcher);
  const {mountPositionGeneration}=await app.entry('position-generation.js');
  let state=saved, draft={mode:'forward',prompt:'',seed:'',raw_frames:124,count:1,reference_ids:[],reference_mode:'inherit',width:1024,height:576};
  const calls=[],messages=[];
  const composer=mountPositionGeneration({sequence:{state:()=>state,positionDraft:()=>draft,setPositionDraft:changes=>{draft={...draft,...changes};}},
    getJSON:async url=>{calls.push(url);return {available:true,duration_options:[]};},byId:id=>app.elements.get(id),
    duration:{reset(){},unavailable(){messages.push('unavailable');},ready(){},valid:()=>false},onUpdate(){},onMessage(){}});
  await composer.open({left:A,right:null,mode:'forward'},draft);
  assert.equal(calls.length,0,'a job UUID is never probed as a native Take');
  assert.match(app.elements.get('native-readiness').textContent,/video only/i);
  assert.equal(composer.valid(),false);
  draft={...draft,mode:'root',reference_mode:'custom'};
  await composer.open({left:A,right:null,mode:'root'},draft);
  assert.equal(calls.length,1,'independent New take is allowed next to video-only media');
});

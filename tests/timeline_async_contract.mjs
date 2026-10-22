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
  load(){if(this.src)queueMicrotask(()=>this.onloadedmetadata?.());}
  close(){this.open=false;void this.fire('close');} showModal(){this.open=true;}
  querySelectorAll(){return [];}
  focus(){} select(){} click(){return this.fire('click');}
}
async function environment(fetcher,search='',initialStorage={}) {
  const markup=readFileSync(resolve(root,'src/templates/timeline.html'),'utf8');
  const elements=new Map([...markup.matchAll(/id="([^"]+)"/g)].map(([,id])=>[id,new Element()]));
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
    if(url.endsWith('/readiness'))return response({verified:true,extend:true,reason:null});
    if(extra){const value=await extra(url,options);if(value)return value;}
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
test('library preview exposes direction and references; placement is explicit and never generates',async()=>{
  const backend=nativeBackend(),app=await environment(backend.fetcher);
  await app.entry('continuity-studio.js');await flush();
  const e=app.elements;
  await e.get('native-takes').children[0].children[0].click();await flush();
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

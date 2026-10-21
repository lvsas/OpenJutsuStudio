// Shipped ES modules run in isolated DOMs. Fixtures below are unit-test responses,
// not evidence of browser layout, valid decoded video, OS sharing or backend writes.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {resolve, dirname} from 'node:path';
import {File} from 'node:buffer';
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
  focus(){} select(){} click(){return this.fire('click');}
}
async function environment(fetcher,search='') {
  const markup=readFileSync(resolve(root,'src/templates/timeline.html'),'utf8');
  const elements=new Map([...markup.matchAll(/id="([^"]+)"/g)].map(([,id])=>[id,new Element()]));
  const notices=[],events={},storage=new Map();const location={search};
  const document={getElementById:id=>elements.get(id),createElement:()=>new Element()};
  const context=vm.createContext({document,location,console,URLSearchParams,URL,Response,File,
    Blob,AbortSignal,queueMicrotask,fetch:fetcher,setTimeout,clearTimeout,
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
  return {elements,notices,entry};
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

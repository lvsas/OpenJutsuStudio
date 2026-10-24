// Native export UI contracts. No inference, browser layout or OS-sharing claim.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32),D='d'.repeat(32);
const workspace=()=>({project_id:A,title:'Chosen native path',revision:12,
  placements:[{placement_id:B,take_id:D},{placement_id:C,take_id:D}],drafts:{[B]:{prompt:'PRIVATE'}}});
const receipt=(overrides={})=>({export_id:D,project_id:A,revision:12,source:'native',
  placement_ids:[B,C],status:'ready',error:null,status_url:`/api/timeline/exports/${D}`,
  preview_url:`/api/timeline/exports/${D}/media`,download_url:`/api/timeline/exports/${D}/media?download=true`,...overrides});
const response=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
const flush=async()=>{for(let i=0;i<15;i++)await new Promise(r=>setImmediate(r));};
class Element {
  constructor(){this.listeners={};this.hidden=false;this.disabled=false;this.open=false;this.value='';}
  addEventListener(e,f){(this.listeners[e]||=[]).push(f);}
  async click(){for(const f of this.listeners.click||[])await f({preventDefault(){}});}
  pause(){this.paused=true;}removeAttribute(k){delete this[k];}getAttribute(k){return this[k]??null;}
  showModal(){this.open=true;}close(){this.open=false;}focus(){}select(){}
}
async function environment(fetcher) {
  const elements=new Map([...readFileSync(resolve(root,'src/templates/timeline.html'),'utf8').matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  const notices=[],storage=new Map(),modules=new Map();
  const context=vm.createContext({console,Response,URL,AbortSignal,fetch:fetcher,setTimeout,clearTimeout,
    document:{getElementById:id=>elements.get(id),querySelectorAll:()=>['native-video','candidate-video','timeline-video','export-video'].map(id=>elements.get(id))},window:{addEventListener(){}},navigator:{},
    localStorage:{setItem:(k,v)=>storage.set(k,v)},Blob,File:class{}});
  async function load(path){
    path=resolve(path);if(modules.has(path))return modules.get(path);
    const m=new vm.SourceTextModule(readFileSync(path,'utf8'),{context,identifier:path});modules.set(path,m);
    await m.link((s,p)=>load(resolve(dirname(p.identifier),s)));return m;
  }
  async function entry(name){const m=await load(resolve(root,'src/static',name));await m.evaluate();return m.namespace;}
  return {elements,notices,storage,entry,notify:text=>notices.push(text)};
}

test('native export sends revision only and uses the shared ready artifact',async()=>{
  const calls=[];const app=await environment(async(url,options={})=>{calls.push({url,options});return response(receipt());});
  const {TimelineExport}=await app.entry('timeline-export-ui.js');const ui=new TimelineExport(app.notify);
  app.elements.get('native-video').paused=false;app.elements.get('candidate-video').paused=false;
  const original=workspace();await ui.open(original,'native');
  assert.equal(app.elements.get('native-video').paused,true);assert.equal(app.elements.get('candidate-video').paused,true);
  assert.equal(calls[0].url,`/api/timeline/projects/${A}/native-workspace/export`);
  assert.equal(calls[0].options.body,'{"revision":12}');
  assert.equal(calls[0].options.method,'POST');
  assert.equal(app.elements.get('export-video').src,receipt().preview_url);
  assert.equal(app.elements.get('download-export').href,receipt().download_url);
  assert.equal(ui.project.drafts,undefined);
  original.revision=99;original.placements.reverse();
  assert.equal(ui.project.revision,12);assert.equal(ui.project.placements[0].placement_id,B);
  assert.equal(app.storage.get(`opengenjutsu.timeline.export.native.${A}`),D);
});

test('native export refuses legacy receipts and changed ordered paths',async()=>{
  for(const invalid of [receipt({source:'legacy'}),receipt({placement_ids:[C,B]}),receipt({placement_ids:[B,B]})]){
    const app=await environment(async()=>response(invalid));const {TimelineExport}=await app.entry('timeline-export-ui.js');
    const ui=new TimelineExport(app.notify);await ui.open(workspace(),'native');
    assert.match(app.elements.get('export-status').textContent,/source|path/i);
    assert.equal(app.elements.get('export-video').src,undefined);
    assert.equal(app.elements.get('download-export').hidden,true);
  }
});

test('queued native export polls identity without submitting again',async()=>{
  const calls=[];const app=await environment(async(url,options={})=>{calls.push({url,options});return response(receipt(options.method==='POST'?{status:'queued',preview_url:null,download_url:null}:{}));});
  const {TimelineExport}=await app.entry('timeline-export-ui.js');const ui=new TimelineExport(app.notify);
  await ui.open(workspace(),'native');await flush();
  assert.equal(ui.current.status,'ready');assert.equal(calls.filter(c=>c.options.method==='POST').length,1);
  assert.equal(calls[1].url,receipt().status_url);
});

test('legacy and native share one dialog controller and keep their source on retry',async()=>{
  const calls=[];let fail=true;
  const app=await environment(async(url,options={})=>{calls.push({url,options});
    if(fail)return response(receipt({status:'error',error:'Synthetic export failure',preview_url:null,download_url:null}));
    const value=receipt();delete value.source;delete value.placement_ids;return response(value);});
  const {getTimelineExport}=await app.entry('timeline-export-ui.js');const first=getTimelineExport(app.notify),second=getTimelineExport(app.notify);
  assert.equal(first,second);assert.equal(app.elements.get('retry-export').listeners.click.length,1);
  await first.open(workspace(),'native');await app.elements.get('retry-export').click();
  assert.equal(calls.length,2);assert.ok(calls.every(c=>c.url.endsWith('/native-workspace/export')));
  fail=false;await second.open({project_id:A,title:'Legacy cut',revision:12,clips:[{clip_id:B}]});
  assert.equal(calls.at(-1).url,`/api/timeline/projects/${A}/export`);
  assert.equal(first.current.source,undefined);assert.equal(first.source,'legacy');
});

test('native toolbar flushes saves and blocks a changed project before any POST',async()=>{
  let current=workspace(),saved=false,mode='ok',posts=0;
  const app=await environment(async()=>{posts++;assert.equal(saved,true);return response(receipt());});
  const seq={state:()=>structuredClone(current),editable:()=>true,flush:async()=>{saved=true;if(mode==='change')current={...current,project_id:C};}};
  const {mountNativeExport}=await app.entry('native-sequence-export.js');const button=app.elements.get('native-export');
  mountNativeExport({sequence:seq,button,notify:app.notify});await button.click();assert.equal(posts,1);
  mode='change';saved=false;await button.click();assert.equal(posts,1);
  assert.match(app.notices.at(-1),/sequence changed/i);
});

test('empty native workspace cannot export a hidden legacy cut',async()=>{
  const app=await environment(()=>{throw Error('No export expected');});
  const {mountNativeExport}=await app.entry('native-sequence-export.js');const button=app.elements.get('native-export');
  mountNativeExport({sequence:{state:()=>({placements:[],clips:[{}]}),editable:()=>true},button,notify:app.notify});
  assert.equal(button.disabled,true);await button.click();
});

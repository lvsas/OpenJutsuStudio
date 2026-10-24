import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const source=fs.readFileSync('src/static/project-session.js','utf8');
const A='a'.repeat(32),B='b'.repeat(32),J='c'.repeat(32);
function session({query='',stored={},draft=null,rows=[],fetchOverride}={}) {
  const calls=[],events=new Map(),cache=new Map(Object.entries(stored));
  const location=new URL('http://localhost/h3'+query);
  const window={addEventListener:(key,fn)=>{events.set(key,fn);},dispatchEvent:event=>events.get(event.type)?.(event)};
  const fetch=async(url,options={})=>{
    calls.push([url,options]);
    const custom=fetchOverride?.(url,options);if(custom)return custom;
    let data;
    if(url==='/api/timeline/draft')data={project:options.method==='POST'?{project_id:A}:draft};
    else if(url.endsWith('/assets')){const id=url.split('/').at(-2);data={project_id:id,revision:0,assets:{characters:[],jobs:id===A?[J]:[],takes:[]},jobs:id===A?rows:[]};}
    else {const id=url.split('/').at(-1);data={project_id:id,title:id===A?'A':'B',is_draft:false};}
    return {ok:true,json:async()=>data};
  };
  const document={readyState:'loading',addEventListener(){},querySelectorAll:()=>[]};
  const history={replaceState:(_a,_b,url)=>{location.href=new URL(url,location).href;}};
  vm.runInNewContext(source,{window,document,location,history,fetch,URL,URLSearchParams,structuredClone,
    CustomEvent:class{constructor(type){this.type=type;}},localStorage:{getItem:key=>cache.get(key)||null,setItem:(key,val)=>cache.set(key,val)}});
  return {scope:window.OpenGenjutsuProject,calls,events,location};
}
test('empty navigation is readonly; concurrent explicit ensure creates one draft',async()=>{
  const {scope,calls}=session();await scope.ready;assert.equal(scope.id(),null);assert.equal(calls.length,1);
  const ids=await Promise.all([scope.ensure(),scope.ensure()]);assert.deepEqual(ids,[A,A]);
  assert.equal(calls.filter(([,options])=>options.method==='POST').length,1);
  assert.equal(scope.storageKey('completed'),'completed.project.'+A);
});
test('explicit URL project beats remembered context; restoration stays scoped',async()=>{
  const {scope}=session({query:'?project_id='+A,stored:{'opengenjutsu.workspace.project':B},rows:[{job_id:J,engine:'minimax-h3',status:'done'}]});
  await scope.ready;assert.equal(scope.id(),A);assert.equal(scope.recovery('minimax-h3').job_id,J);
  assert.equal(scope.recovery('ltx25-ripple'),null);assert.equal(scope.containsJob(J),true);
  assert.throws(()=>scope.acceptJob(J,B,'minimax-h3'),/another project/);
});
test('malformed and duplicate URL context fails closed without requests',async()=>{
  for(const query of ['?project_id=../bad','?project_id='+A+'&project_id='+B,'?job_id=bad']){
    const {scope,calls}=session({query});await assert.rejects(scope.ready,/invalid/);assert.equal(calls.length,0);
    await assert.rejects(scope.ensure(),/invalid/);
  }
});
test('old project response cannot replace current context after switching',async()=>{
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  const s=session({query:'?project_id='+A,fetchOverride:url=>url==='/api/timeline/projects/'+A?gate:null});
  s.location.search='?project_id='+B;s.events.get('opengenjutsu:project-context')();
  await new Promise(resolve=>setImmediate(resolve));
  release({ok:true,json:async()=>({project_id:A,title:'Old A'})});await s.scope.ready;
  assert.equal(s.scope.id(),B);assert.equal(s.scope.containsJob(J),false);
});
test('server-owned queued jobs can resume without browser job storage',async()=>{
  const {scope}=session({query:'?project_id='+A,rows:[{job_id:J,engine:'ltx25-ripple',status:'queued'}]});
  await scope.ready;assert.equal(scope.recovery('ltx25-ripple').job_id,J);
  assert.equal(scope.storageKey('opengenjutsu.h3.current-job'),'opengenjutsu.h3.current-job.project.'+A);
});

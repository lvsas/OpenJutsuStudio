import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
function environment(){
  class Node {
    constructor(id,src=''){this.id=id;this.src=src;this.hidden=false;this.pauses=0;this.attrs={};}
    pause(){this.pauses++;}getAttribute(k){return k==='src'?(this.src||null):this.attrs[k]??null;}
    setAttribute(k,v){this.attrs[k]=v;}scrollIntoView(){this.scrolled=true;}focus(){this.focused=true;}
  }
  const nodes=new Map();for(const id of ['stage-empty','state','inspection-status','inspection-preview'])nodes.set('h3-'+id,new Node('h3-'+id));
  for(const kind of ['source','reference','result'])nodes.set('h3-'+kind+'-preview',new Node('h3-'+kind+'-preview','/saved/'+kind));
  for(const id of ['reference','reference-2'])nodes.set('h3-take-'+id+'-preview',new Node('h3-take-'+id+'-preview','/saved/'+id));
  const cards=['source','reference','reference-2','result'].map(kind=>{const n=new Node('h3-take-'+kind+'-card');n.dataset={h3Stage:kind==='reference-2'?'reference':kind};return n;});
  const context=vm.createContext({console,document:{getElementById:id=>nodes.get(id),querySelectorAll:()=>cards},fetch:()=>{throw Error('Inspection cannot fetch or submit');}});
  const module=new vm.SourceTextModule(readFileSync('src/static/h3-http.js','utf8'),{context});
  return {module,nodes,cards};
}
async function setup(){const app=environment();await app.module.link(()=>{throw Error('Unexpected module dependency');});await app.module.evaluate();return app;}
test('explicit inspection reveals and focuses the existing source preview and pauses result',async()=>{
  const {module,nodes,cards}=await setup();assert.equal(module.namespace.inspectTakeStage('source'),true);
  assert.equal(nodes.get('h3-source-preview').hidden,false);assert.equal(nodes.get('h3-result-preview').hidden,true);
  assert.equal(nodes.get('h3-result-preview').pauses,1);
  assert.equal(nodes.get('h3-inspection-preview').scrolled,true);assert.equal(nodes.get('h3-inspection-preview').focused,true);
  assert.equal(nodes.get('h3-inspection-status').hidden,false);assert.match(nodes.get('h3-inspection-status').textContent,/source/i);
  assert.equal(cards[0].attrs['aria-pressed'],'true');
});
test('two saved references select their own media without changing reference identity',async()=>{
  const {module,nodes,cards}=await setup();const run=module.namespace.inspectTakeStage;
  assert.equal(run('reference',true),true);assert.equal(nodes.get('h3-reference-preview').src,'/saved/reference-2');assert.equal(cards[2].attrs['aria-pressed'],'true');
  assert.equal(run('reference',false),true);assert.equal(nodes.get('h3-reference-preview').src,'/saved/reference');assert.equal(cards[1].attrs['aria-pressed'],'true');
  assert.equal(nodes.get('h3-take-reference-2-preview').src,'/saved/reference-2');
});
test('missing saved media refuses safely; ordinary rendering never scrolls the page',async()=>{
  const {module,nodes}=await setup();nodes.get('h3-source-preview').src='';
  assert.equal(module.namespace.inspectTakeStage('source'),false);assert.equal(nodes.get('h3-inspection-preview').scrolled,undefined);
  module.namespace.setStage('result');assert.equal(nodes.get('h3-inspection-preview').scrolled,undefined);
  assert.equal(nodes.get('h3-inspection-status').hidden,true);
});

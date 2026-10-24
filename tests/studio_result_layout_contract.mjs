import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
function setup(){
 const classes=new Set(),title={textContent:'Build your transformation'},fields={seed:'7',source:'unmodified'};
 const panel={querySelector:()=>title,fields},actions={hidden:true},stage={querySelector:()=>actions};
 const grid={children:[panel,stage],querySelector:s=>s==='.recipe-panel'?panel:stage,
  classList:{toggle:(s,v)=>v?classes.add(s):classes.delete(s)},insertBefore(a,b){this.children=this.children.filter(n=>n!==a);this.children.splice(this.children.indexOf(b),0,a);}};
 let changes,visibility,disconnects=0,removed=0;const events={};
 const mq={matches:true,addEventListener:(_,fn)=>changes=fn,removeEventListener:()=>removed++};
 const context=vm.createContext({document:{querySelectorAll:()=>[grid]},
  MutationObserver:class{constructor(fn){visibility=fn;}observe(){}disconnect(){disconnects++;}},
  window:{matchMedia:()=>mq,addEventListener:(k,fn)=>events[k]=fn,removeEventListener(){}}});
 vm.runInContext(readFileSync('src/static/studio-utils.js','utf8'),context);
 return {utils:context.window.OpenGenjutsuStudio,grid,panel,stage,actions,title,fields,classes,mq,
  changed:()=>changes(),visibility:()=>visibility(),events,counts:()=>({disconnects,removed})};
}
test('empty studio keeps creation first; a saved result moves the same existing nodes, without changing inputs',()=>{
 const a=setup();a.utils.mountResultLayout();assert.equal(a.grid.children[0],a.panel);
 a.actions.hidden=false;a.visibility();assert.equal(a.grid.children[0],a.stage);assert.equal(a.grid.children[1],a.panel);
 assert.equal(a.title.textContent,'Create a new swap');assert.ok(a.classes.has('has-saved-result'));
 assert.deepEqual(a.fields,{seed:'7',source:'unmodified'});
 a.actions.hidden=true;a.visibility();assert.equal(a.grid.children[0],a.panel);assert.equal(a.title.textContent,'Build your transformation');
});
test('desktop restores the original two-column DOM order without forgetting the saved result',()=>{
 const a=setup();a.actions.hidden=false;a.utils.mountResultLayout();assert.equal(a.grid.children[0],a.stage);
 a.mq.matches=false;a.changed();assert.equal(a.grid.children[0],a.panel);assert.ok(a.classes.has('has-saved-result'));
 a.mq.matches=true;a.changed();assert.equal(a.grid.children[0],a.stage);
});
test('mounting is idempotent and browser back-forward caching keeps the observer alive',()=>{
 const a=setup();a.utils.mountResultLayout();a.utils.mountResultLayout();a.events.pagehide({persisted:true});
 assert.deepEqual(a.counts(),{disconnects:0,removed:0});a.actions.hidden=false;a.visibility();assert.equal(a.grid.children[0],a.stage);
 a.events.pagehide({persisted:false});assert.deepEqual(a.counts(),{disconnects:1,removed:1});
});

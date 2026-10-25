// Real LTX adapter + shared selector, isolated from backend/GPU.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {File} from 'node:buffer';
class Element {
  constructor() { Object.assign(this, {value:'',disabled:false,hidden:false,events:new Map(),attrs:{},files:[],currentTime:0,plays:0,pauses:0}); }
  addEventListener(n,fn) { if(!this.events.has(n)) this.events.set(n,new Set()); this.events.get(n).add(fn); }
  removeEventListener(n,fn) { this.events.get(n)?.delete(fn); }
  emit(n) { for(const fn of [...(this.events.get(n)||[])]) fn(); }
  getAttribute(n) { return n==='src'?this.src:this.attrs[n]; }
  setAttribute(n,v) { this.attrs[n]=v; }
  setCustomValidity(v) { this.validity=v; }
  focus() {}
  load() { this.currentSrc=this.src; }
  pause() { this.pauses++; }
  play() { this.plays++; return Promise.resolve(); }
}
const html=readFileSync(new URL('../src/templates/index.html',import.meta.url),'utf8');
const nodes=new Map([...html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)].map(m=>{
  const e=new Element(); e.hidden=/\bhidden\b/.test(m[0]); e.disabled=/\bdisabled\b/.test(m[0]); return [m[1],e];
}));
const events=new EventTarget(), stages=[];
globalThis.CustomEvent=class extends Event { constructor(name,opts={}) { super(name); this.detail=opts.detail; } };
globalThis.window={OpenGenjutsuStudio:{clipLimit:15},addEventListener:(...a)=>events.addEventListener(...a),dispatchEvent:e=>events.dispatchEvent(e)};
globalThis.document={getElementById:id=>nodes.get(id)};
events.addEventListener('opengenjutsu:select-stage',e=>stages.push(e.detail.stage));
let network=0; globalThis.fetch=()=>{network++;throw new Error('No requests allowed');};
await import('../src/static/ltx-source-clip.js');
const clip=window.OpenGenjutsuClip, source=nodes.get('video'), media=nodes.get('source-preview');
async function select(duration) {
  source.files=[new File(['local source'],'source.mp4',{type:'video/mp4'})];
  media.src='/api/jobs/old/source'; media.currentSrc=media.src;
  source.emit('change'); // Adapter listener may run before the existing source owner.
  media.src=URL.createObjectURL(source.files[0]); media.currentSrc=media.src;
  await Promise.resolve();
  media.duration=duration; media.emit('loadedmetadata');
}
await select(8); assert.equal(nodes.get('source-clip').hidden,true); assert.equal(clip.valid,true);
let data=new FormData(); clip.appendTo(data); assert.equal([...data].length,0);
await select(15); assert.equal(nodes.get('source-clip').hidden,true);
await select(22); assert.equal(nodes.get('source-clip').hidden,false); assert.equal(clip.valid,true);
assert.equal(nodes.get('clip-end').value,'15');
nodes.get('clip-start').value='2'; nodes.get('clip-end').value='5'; nodes.get('clip-end').emit('input');
data=new FormData(); clip.appendTo(data); assert.equal(data.get('clip_start_seconds'),'2'); assert.equal(data.get('clip_end_seconds'),'5');
media.src='/api/jobs/saved/source'; media.currentSrc=media.src; media.duration=3; media.emit('loadedmetadata');
assert.equal(clip.duration,22);
await clip.play(); assert.match(media.src,/^blob:/); assert.equal(media.currentTime,2); assert.equal(stages.at(-1),'source');
media.currentTime=5.1; media.emit('timeupdate'); assert.equal(media.currentTime,5); assert.ok(media.pauses>0);
clip.setLocked(true); assert.equal(nodes.get('clip-start').disabled,true);
clip.setLocked(false); nodes.get('clip-end').value='18'; nodes.get('clip-end').emit('input'); assert.equal(clip.valid,false);
clip.setLimit(undefined); assert.equal(clip.valid,false);
assert.equal(network,0);
console.log('LTX source excerpt adapter passed: short hidden, long explicit, original restored, bounds, locks, no requests.');

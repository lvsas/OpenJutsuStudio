import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// A small DOM double exercising decisions, async races and sharing (browser QA covers layout).
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.hidden = false; this.disabled = false; this.attrs = {};
    this.listeners = {}; this.nodes = {}; this.open = false; this.isConnected = true;
    this.value = ''; this.textContent = ''; this.classes = new Set();
    const classes = this.classes;
    this.classList = {add: c => classes.add(c), remove: c => classes.delete(c),
      replace: (a, b) => { classes.delete(a); classes.add(b); }};
  }
  set innerHTML(value) { this.markup = value; }
  querySelector(selector) { return this.nodes[selector] ||= new Element(selector.includes('video') ? 'video' : 'div'); }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; if(k === 'src') this.src = ''; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async fire(name, extra={}) { for (const fn of this.listeners[name] || []) await fn({target:this, ...extra}); }
  showModal() { this.open = true; }
  // Browsers queue the close event; a synchronous double hides the close/reopen race.
  close() { this.open = false; setImmediate(() => this.fire('close')); }
  pause() { this.paused = true; }
  load() {}
  play() { this.played = true; return Promise.resolve(); }
  focus() { this.focused = true; }
  select() { this.selected = true; }
}
const flush = async () => { for(let i=0;i<12;i++) await new Promise(r=>setImmediate(r)); };
const source = fs.readFileSync(new URL('../src/static/share-reel.js', import.meta.url), 'utf8');
function harness() {
  let dialog, calls = [], requests = [], shareCalls = [];
  const nav = {};
  const document = {activeElement: new Element('button'), body: new Element('body'),
    createElement(tag) { assert.equal(tag, 'dialog', 'Preview must never create an export anchor'); return dialog = new Element(tag); }};
  document.body.append = () => {};
  const context = {window:{}, document, navigator:nav, location:{origin:'https://studio.test'}, URL, File, AbortSignal,
    setTimeout: fn => setImmediate(fn),
    fetch(url, opts) { calls.push({url, opts}); return new Promise((resolve,reject) => requests.push({resolve,reject})); }};
  vm.runInNewContext(source, context);
  const artifact = 'a'.repeat(64);
  const manifest = id => ({job_id:id, artifact_id:artifact, status:'ready', layout:'social', renderer_version:'social-v2', filename:`opengenjutsu-${id}-social.mp4`,
    status_url:`/api/jobs/${id}/reels/${artifact}`,
    preview_url:`/api/jobs/${id}/reels/${artifact}/media`,
    download_url:`/api/jobs/${id}/reels/${artifact}/media?download=true`});
  return {context, nav, calls, requests, shareCalls, manifest,
    open(id) { context.window.OpenGenjutsuShare.open({jobId:id,resultUrl:`/api/jobs/${id}/result`,returnFocus:document.activeElement}); },
    get dialog(){return dialog;}, q(name){return dialog.querySelector(`.share-reel-${name}`);},
    finish(id) { requests.shift().resolve({ok:true,json:async()=>manifest(id)}); }};
}
{
  const h = harness(); h.open('take-a');
  assert.equal(h.dialog.open,true); assert.match(h.q('status').textContent,/Making your before-and-after/);
  assert.equal(h.q('actions').hidden,true); assert.equal(h.calls.length,1);
  h.finish('take-a'); await flush();
  assert.match(h.q('video').src,/\/reels\/[a-f0-9]{64}\/media/); assert.equal(h.q('actions').hidden,false);
  assert.equal(h.q('native').hidden,true); assert.match(h.q('download').href,/download=true/);
  await h.q('copy').fire('click'); assert.equal(h.q('caption').selected,true);
  h.dialog.close(); await flush(); assert.equal(h.q('video').paused,true); assert.equal(h.context.document.activeElement.focused,true);
  h.open('take-a'); await flush(); assert.equal(h.calls.length,1,'Reopen must reuse artifact');
}
{
  const h = harness(); h.open('old-take'); h.dialog.close(); h.open('new-take');
  h.finish('old-take'); await flush(); assert.equal(h.q('video').src, '');
  h.finish('new-take'); await flush(); assert.match(h.q('video').src,/new-take/);
}
{
  const h=harness(); h.open('retry-take'); h.requests.shift().reject(new Error('Network offline')); await flush();
  assert.equal(h.q('retry').hidden,false); assert.equal(h.q('actions').hidden,true);
  await h.q('retry').fire('click'); assert.equal(h.calls.length,2); h.finish('retry-take'); await flush();
  assert.equal(h.q('retry').hidden,true); assert.equal(h.q('actions').hidden,false);
}
{
  const h=harness(); h.nav.canShare=()=>true; h.nav.share=async data=>h.shareCalls.push(data);
  h.open('native-take'); h.finish('native-take'); await flush();
  assert.equal(h.q('native').hidden,true,'No share action until file is prepared');
  h.requests.shift().resolve({ok:true,headers:new Map([['content-length','4']]),blob:async()=>new Blob(['test'],{type:'video/mp4'})});
  await flush(); assert.equal(h.q('native').hidden,false); assert.equal(h.shareCalls.length,0,'No automatic native share');
  await h.q('native').fire('click'); assert.equal(h.shareCalls.length,1); assert.equal(h.shareCalls[0].files[0].size,4);
  h.nav.share=async()=>{const e=new Error();e.name='AbortError';throw e;};
  await h.q('native').fire('click'); assert.match(h.q('status').textContent,/cancelled/);
}
{
  const h=harness(); h.open('unsafe');
  h.requests.shift().resolve({ok:true,json:async()=>({...h.manifest('unsafe'),preview_url:'https://evil.test/movie.mp4'})});
  await flush(); assert.equal(h.q('retry').hidden,false); assert.equal(h.q('actions').hidden,true);
}
{
  const h=harness(); h.open('queued-take');
  h.requests.shift().resolve({ok:true,json:async()=>({...h.manifest('queued-take'),status:'queued',preview_url:null,download_url:null})});
  await flush(); assert.equal(h.q('actions').hidden,true); assert.equal(h.calls.length,2);
  assert.equal(h.calls[1].url,h.manifest('queued-take').status_url);
  h.finish('queued-take'); await flush(); assert.equal(h.q('actions').hidden,false);
}
{
  // A queued close event must not tear down a preview that was reopened immediately after.
  const h=harness(); h.open('first-take'); h.finish('first-take'); await flush();
  h.dialog.close(); h.open('second-take'); await flush();
  assert.equal(h.dialog.open,true,'reopened preview stays open');
  assert.equal(h.q('video').src,'','the previous session is cleared before the new one loads');
  assert.ok(h.context.document.body.classes.has('share-reel-open'),'scroll lock belongs to the open session');
  h.finish('second-take'); await flush();
  assert.match(h.q('video').src,/second-take/,'the closed session cannot erase the new preview');
  assert.equal(h.context.document.activeElement.focused,undefined,'focus is not yanked by the stale close');
}
console.log('Share reel UI: preview, cache, stale response, retry, clipboard fallback, explicit native sharing, async polling, URL validation PASS');

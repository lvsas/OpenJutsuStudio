import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// DOM double for decisions/races; not proof of browser layout or real share-sheet behavior.
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.hidden = false; this.disabled = false; this.attrs = {};
    this.listeners = {}; this.nodes = {}; this.open = false; this.isConnected = true;
    this.value = ''; this.textContent = ''; this.classes = new Set();
    const classes = this.classes;
    this.classList = {add: c => classes.add(c), remove: c => classes.delete(c),
      replace: (a, b) => { classes.delete(a); classes.add(b); }};
  }
  set innerHTML(value) {
    this.markup = value;
    // Register real markup classes/attributes; unknown selectors must not invent controls.
    for (const match of value.matchAll(/<([a-z][\w-]*)\b([^>]*)>/g)) {
      const node = new Element(match[1]);
      for (const attr of match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
        node.setAttribute(attr[1], attr[2] ?? '');
      }
      node.hidden = Object.hasOwn(node.attrs, 'hidden');
      for (const name of (node.attrs.class || '').split(/\s+/).filter(Boolean)) {
        node.classes.add(name); this.nodes[`.${name}`] = node;
      }
    }
  }
  querySelector(selector) { return this.nodes[selector] || null; }
  setAttribute(k, v) { this.attrs[k] = v; if (['href', 'target', 'rel', 'download'].includes(k)) this[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; if(['src', 'href'].includes(k)) this[k] = ''; }
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
    open(id, options = {}) { context.window.OpenGenjutsuShare.open({jobId:id,resultUrl:`/api/jobs/${id}/result`,returnFocus:document.activeElement,...options}); },
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
  assert.match(h.q('help').textContent, /Attach downloaded MP4 in X/, 'Native support preserves manual attachment guidance');
  h.q('caption').value = 'My edited native caption'; await h.q('caption').fire('input');
  await h.q('native').fire('click'); assert.equal(h.shareCalls.length,1); assert.equal(h.shareCalls[0].files[0].size,4);
  assert.equal(h.shareCalls[0].text, 'My edited native caption');
  h.nav.share=async()=>{const e=new Error();e.name='AbortError';throw e;};
  await h.q('native').fire('click'); assert.match(h.q('status').textContent,/cancelled/);
  assert.equal(h.q('native').disabled, false);
  h.nav.share=async()=>{throw new Error('Not allowed');};
  await h.q('native').fire('click');
  assert.match(h.q('status').textContent, /Download the reel and copy your caption instead/);
  assert.equal(h.q('native').disabled, false);
  assert.match(h.q('download').href, /download=true/);
  assert.equal(new URL(h.q('x').href).searchParams.get('text'), 'My edited native caption');
  h.open('native-next');
  assert.equal(h.q('native').hidden, true); assert.equal(h.q('actions').hidden, true);
  assert.equal(h.q('x').href || '', '', 'Native sharing cannot retain a previous X intent');
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
{
  const h = harness(), copied = [];
  h.nav.clipboard = {writeText: async text => copied.push(text)};
  h.open('x-take', {caption: 'My own caption'});
  assert.equal(h.q('caption').value, 'My own caption', 'Caller caption remains the default');
  assert.ok(h.q('contest'), 'Contest caption must be explicitly available in the shared modal');
  assert.equal(h.q('x').tagName, 'a', 'X opens through a real link, not a popup or API');
  assert.equal(h.q('x').href || '', '', 'No stale intent while preparing');
  assert.equal(h.q('x').target, '_blank');
  assert.deepEqual(h.q('x').rel.split(/\s+/).sort(), ['noopener', 'noreferrer']);
  let prevented = false;
  await h.q('x').fire('click', {preventDefault: () => { prevented = true; }});
  assert.equal(prevented, true, 'Pending reel must not open X');
  await h.q('contest').fire('click');
  const contest = h.q('caption').value;
  assert.match(contest, /@ComfyUI/);
  assert.match(contest, /https:\/\/comfy\.org\/open-source-higgsfield/);
  assert.deepEqual(contest.match(/@[A-Za-z0-9_]+/g), ['@ComfyUI'], 'No invented partner handles');
  assert.ok(contest.length < 280, 'Short contest caption');
  assert.doesNotMatch(contest, /github|open.?weights|licen[cs]e/i);
  assert.equal(h.q('x').href || '', '', 'Opt-in does not enable an unready reel');
  h.finish('x-take'); await flush();
  assert.equal(h.q('actions').hidden, false);
  assert.equal(new URL(h.q('x').href).searchParams.get('text'), contest, 'Pending edits survive readiness');
  const caption = 'Mon swap é & #? + 100%\n@ComfyUI 🎬';
  h.q('caption').value = caption;
  await h.q('caption').fire('input');
  const intent = new URL(h.q('x').href);
  assert.equal(intent.origin, 'https://twitter.com');
  assert.equal(intent.pathname, '/intent/tweet');
  assert.equal(intent.search, '?text=' + encodeURIComponent(caption), 'Actual edited caption is percent-encoded');
  assert.deepEqual([...intent.searchParams], [['text', caption]], 'Text only: no media, result or URL parameter');
  assert.doesNotMatch(h.q('x').href, /studio\.test|localhost|\/api\/jobs|\/media/);
  assert.match(h.q('help').textContent, /Attach (?:the )?downloaded MP4 in X/);
  assert.match(h.q('help').textContent, /text only/i);
  assert.deepEqual(copied, [], 'No automatic clipboard writes');
  assert.equal(h.shareCalls.length, 0, 'No automatic native sharing');
  assert.deepEqual(h.calls.map(c => [c.url, c.opts?.method]), [
    ['/api/jobs/x-take/reveal?layout=social', 'POST']
  ], 'No social API or publishing request');
  await h.q('x').fire('click');
  assert.equal(h.calls.length, 1, 'X click does not publish or upload');
  assert.deepEqual(copied, [], 'X does not silently copy the caption');
  await h.q('copy').fire('click'); assert.deepEqual(copied, [caption]);
  await h.q('contest').fire('click');
  assert.equal(h.q('caption').value, contest, 'Only the opt-in button replaces the edited caption');
  assert.equal(new URL(h.q('x').href).searchParams.get('text'), contest, 'Ready contest action updates X immediately');
  h.open('x-next');
  assert.equal(h.q('actions').hidden, true);
  assert.equal(h.q('x').href || '', '', 'Ready-to-pending transition clears old caption intent');
  assert.doesNotMatch(h.q('caption').value, /@ComfyUI/, 'Contest opt-in does not leak into the next take');
  h.requests.shift().reject(new Error('Offline')); await flush();
  assert.equal(h.q('x').href || '', '', 'Error state cannot expose a stale X intent');
  await h.q('retry').fire('click');
  assert.equal(h.q('x').href || '', '');
  h.finish('x-next'); await flush();
  assert.equal(new URL(h.q('x').href).searchParams.get('text'), h.q('caption').value);
  h.dialog.close(); await flush();
  assert.equal(h.q('x').href || '', '', 'Close clears the external action');
}
console.log('Share reel UI: preview, cache, stale response, retry, clipboard fallback, explicit native sharing, async polling, explicit X intent, opt-in contest caption, URL validation PASS');

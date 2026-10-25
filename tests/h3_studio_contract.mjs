import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {File} from 'node:buffer';
const html = readFileSync(new URL('../src/templates/h3.html', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'DIV') {
    Object.assign(this, {tagName: tag, hidden: false, disabled: false, open: false,
      textContent: '', value: '', files: [], events: {}, listeners: new Map(), attrs: {}, children: [], validity: '', style: {}, plays: 0, pauses: 0,
      classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }}});
  }
  addEventListener(name, fn) {
    this.listeners.set(name, [...(this.listeners.get(name) || []), fn]);
    this.events[name] = (...args) => { let result = this[`on${name}`]?.(...args); for (const f of [...this.listeners.get(name)]) result = f(...args); return result; };
  }
  removeEventListener(name, fn) { this.listeners.set(name, this.listeners.get(name).filter(f => f !== fn)); }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return name === 'src' ? this.src || null : this.attrs[name] || null; }
  removeAttribute(name) { if (name === 'src') this.src = ''; else delete this.attrs[name]; }
  append(node) { this.children.push(node); }
  replaceChildren() { this.children = []; }
  querySelector() { return new Element('SPAN'); }
  get firstElementChild() { return new Element('SPAN'); }
  get lastElementChild() { return new Element('SPAN'); }
  get childElementCount() { return this.children.length; }
  pause() { this.pauses++; }
  play() { this.plays++; return Promise.resolve(); }
  load() {}
  scrollIntoView() { this.scrolled=true; }
  focus() { this.focused=true; }
  set value(value) { this._value = value; if (value === '' && this.type === 'file') this.files = []; }
  get value() { return this._value; }
  click() { if (!this.disabled) return this.events.click?.(); }
  setCustomValidity(value) { this.validity = value; }
  closest() { return elements.get('h3-advanced'); }
}
const elements = new Map();
for (const match of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
  const element = new Element(match[1].toUpperCase());
  element.id = match[3];
  element.name = match[2].match(/\bname="([^"]+)"/)?.[1];
  element.type = match[2].match(/\btype="([^"]+)"/)?.[1];
  element.dataset = {h3Stage: match[2].match(/data-h3-stage="([^"]+)"/)?.[1]};
  element.hidden = /\bhidden\b/.test(match[2]);
  element.disabled = /\bdisabled\b/.test(match[2]);
  element.value = match[2].match(/\bvalue="([^"]*)"/)?.[1] || '';
  elements.set(match[3], element);
}
elements.set('h3-advanced', new Element('DETAILS'));
// LTX parity: source summary after frame, capsule media inside result actions.
for (const kind of ['source', 'reference', 'result']) {
  assert.ok(html.includes(`id="h3-take-${kind}-preview"`), `capsule card ${kind} needs media`);
}
const frameAt = html.indexOf('class="stage-frame"');
const resultActionsAt = html.indexOf('id="h3-result-actions"');
assert.ok(html.indexOf('id="h3-source-summary"') > frameAt, 'source summary must follow the frame');
assert.ok(html.indexOf('id="h3-take-story"') > resultActionsAt, 'capsule must sit inside result actions');
const el = id => elements.get(`h3-${id}`);
globalThis.document = {getElementById: id => elements.get(id), createElement: tag => new Element(tag.toUpperCase()),
  querySelectorAll: selector => selector === '[data-h3-stage]' ? [...elements.values()].filter(e => e.dataset?.h3Stage) : []};
const toasts = [];
const modalOpens = [];
globalThis.window = {addEventListener() {}, OpenGenjutsuShare: {open: options => modalOpens.push(options)}};
globalThis.window.OpenGenjutsuStudio = {showToast: (region, message, type) => toasts.push([region && region.id, message, type])};
await import('../src/static/studio-progress.js');
const store = new Map();
globalThis.localStorage = {getItem: key => store.get(key), setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)};
const tasks = new Map();
let taskId = 0;
globalThis.setTimeout = (fn, ms) => { tasks.set(++taskId, {fn, ms}); return taskId; };
globalThis.clearTimeout = id => tasks.delete(id);
globalThis.setInterval = () => 0;
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data?.ready !== undefined ? {limits:{max_clip_seconds:15},...data} : data});
const calls = [];
let handler = () => response({});
globalThis.fetch = async (url, opts = {}) => { calls.push([url, opts]); return handler(url, opts); };
const {request, validId, jobURL} = await import('../src/static/h3-http.js');
const {H3Take} = await import('../src/static/h3-take.js');
assert.equal(validId('../x'), false);
assert.equal(validId('<script>'), false);
assert.throws(() => jobURL('../x'), /Invalid H3/);
handler = () => response({detail: [{loc: ['body', 'seed'], msg: 'invalid integer'}]}, 422);
await assert.rejects(request('/bad'), /HTTP 422: seed: invalid integer/);
handler = () => response({detail: 'Missing retained input'}, 409);
await assert.rejects(request('/bad'), /HTTP 409: Missing retained input/);
handler = () => ({ok: false, status: 503, json: async () => { throw Error(); }});
await assert.rejects(request('/bad'), /HTTP 503/);
handler = () => { throw Error('offline'); };
await assert.rejects(request('/bad'), /Connection interrupted/);
const id = 'a'.repeat(32), child = 'b'.repeat(32);
const base = {id, result_url: `/api/jobs/${id}/result`, engine: 'minimax-h3', created: 1000, started: 1010, finished: 1070};
const capsule = {job_id: id, engine: 'minimax-h3', recipe: {reference_count: 2, original: '<img onerror=bad>'}};
let job = {...base, status: 'queued', started: null, finished: null};
handler = url => response(url.endsWith('/capsule') ? capsule : job);
const take = new H3Take(() => {}, async () => true);
take.ready = true;
take.watch(id);
await settle();
assert.equal(take.active, true);
assert.match(el('run-title').textContent, /Queued for the H3 studio/);
assert.equal(el('run-overlay').hidden, false);
assert.equal(el('progress-fill').style.width, '4%');
assert.equal(store.get('opengenjutsu.h3.current-job'), id);
assert.equal(el('reference-preview').src, `/api/h3/jobs/${id}/reference`);
job = {...base, status: 'running', finished: null, step: 'h3_assemble', progress: 0.9};
await take.poll(take.epoch);
assert.match(el('run-title').textContent, /Finishing your take/);
assert.equal(el('progress-label').textContent, '90%');
assert.equal(el('run-overlay').hidden, false);
job = {...base, status: 'done', step: 'done', progress: 1};
await take.poll(take.epoch);
assert.equal(take.active, false);
assert.equal(el('run-overlay').hidden, true);
assert.equal(store.has('opengenjutsu.h3.current-job'), false);
assert.equal(store.get('opengenjutsu.h3.completed-job'), id);
assert.match(el('run-title').textContent, /Your swap is ready/);
assert.equal(el('result-preview').src, `/api/jobs/${id}/result`);
assert.equal(el('result-actions').hidden, false);
assert.match(el('capsule-manifest').textContent, /<img onerror=bad>/);
assert.equal(el('replay').disabled, false);
assert.equal(el('take-reference-2-preview').src, `/api/h3/jobs/${id}/reference/1`);
const beforePreview = calls.length;
await el('build-reel').click();
assert.equal(calls.length, beforePreview, 'studio delegates preview without requesting a reel or downloading');
assert.equal(modalOpens.at(-1).jobId, id);
assert.equal(modalOpens.at(-1).resultUrl, base.result_url);
assert.equal(modalOpens.at(-1).returnFocus, el('build-reel'));
assert.match(modalOpens.at(-1).caption, /Same moment. New character/);
const restored = new H3Take(() => {}, async () => true);
restored.resume(); await settle();
assert.equal(restored.id, id, 'refresh must restore a completed take');
assert.equal(el('result-actions').hidden, false);
restored.reset();
assert.equal(el('return-last').hidden, false, 'reset preserves an obvious route back');
assert.equal(store.get('opengenjutsu.h3.completed-job'), id);
await restored.restoreCompleted();
assert.equal(el('result-actions').hidden, false);
handler = url => response(url.endsWith('/replay') ? {job_id: child} : {...base, id: child, status: 'queued'});
await take.replay();
await settle();
assert.equal(take.id, child);
assert.equal(el('result-actions').hidden, true);
assert.ok(calls.some(([url, opts]) => url.endsWith('/replay') && opts.method === 'POST' && !opts.body));
job = {...base, id: child, status: 'error', step: 'h3_error', error: 'Input decode failed'};
handler = () => response(job);
await take.poll(take.epoch);
assert.equal(take.active, false);
assert.match(el('status').textContent, /Input decode failed/);
assert.match(toasts.at(-1)[1], /Input decode failed/);
assert.equal(el('result-actions').hidden, true);
assert.equal(store.get('opengenjutsu.h3.completed-job'), id, 'failed child cannot erase last success');
assert.equal(el('return-last').hidden, false);
handler = () => { throw Error('offline'); };
take.watch(id);
await settle();
assert.equal(take.active, true); // Disconnection is not a terminal job state.
assert.match(toasts.at(-1)[1], /disconnected request does not stop a job/);
take.reset();
store.set('opengenjutsu.ltx.current-job', child);
store.set('opengenjutsu.h3.current-job', '../bad');
take.resume();
assert.equal(store.has('opengenjutsu.h3.current-job'), false);
assert.equal(store.get('opengenjutsu.ltx.current-job'), child);
await settle();
// Old restoration cannot replace a newly selected source.
let resolveOld;
handler = () => new Promise(resolve => { resolveOld = resolve; });
const late = new H3Take(() => {}, async () => true);
late.resume(); late.reset();
resolveOld(response({...base, status: 'done'})); await settle();
assert.equal(el('result-actions').hidden, true);
handler = () => response({...base, engine: 'ltx25-ripple', status: 'done'});
await late.restoreCompleted();
assert.equal(el('result-actions').hidden, true, 'wrong engine cannot restore');
handler = () => response({...base, status: 'done', result_url: null});
await late.restoreCompleted();
assert.equal(el('result-actions').hidden, true, 'missing result cannot restore');
assert.equal(store.get('opengenjutsu.h3.completed-job'), id);
handler = () => response({detail:'Job not found'},404);
late.watch(child); await settle();
assert.equal(late.active, false, 'stale active id must not lock the last completed swap');
assert.equal(el('return-last').disabled, false);
store.delete('opengenjutsu.h3.completed-job');
const storage = globalThis.localStorage;
globalThis.localStorage = {getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}};
handler = url => response(url.endsWith('/capsule') ? capsule : {...base, status:'done'});
const privateTake = new H3Take(() => {}, async () => true);
privateTake.watch(id); await settle();
assert.equal(el('result-actions').hidden, false, 'storage denial must not break generation');
privateTake.reset(); globalThis.localStorage = storage;

// Actual controller, template-derived multipart and advisory readiness.
const NativeFormData = globalThis.FormData;
globalThis.FormData = class extends NativeFormData {
  constructor(form) {
    super();
    if (form) for (const field of elements.values()) {
      if (field.name && !field.disabled) this.append(field.name,
        field.type === 'file' ? field.files[0] || new File([], '') : field.value);
    }
  }
};
el('form').reportValidity = () => !el('seed').validity && !!el('video').files[0] && !!el('reference').files[0];
let ready = true, submitted, releaseSubmit, controllerTake;
const watch = H3Take.prototype.watch;
H3Take.prototype.watch = function(id) { controllerTake = this; return watch.call(this, id); };
handler = (url, opts) => {
  if (url === '/api/h3/readiness') return response({ready, warnings: ['Queue is busy; waiting is not inference.']});
  if (url === '/api/h3/jobs') { submitted = opts.body; return new Promise(resolve => { releaseSubmit = resolve; }); }
  return response({...base, status: 'queued'});
};
await import('../src/static/h3-studio.js');
await settle();
assert.equal(el('submit').disabled, true);
assert.equal(el('readiness').textContent, 'Studio ready');
el('take-reference-preview').src = 'first-reference.png';
el('take-reference-2-preview').src = 'second-reference.png';
el('take-reference-2-card').click();
assert.equal(el('reference-preview').src, 'second-reference.png', 'inspection must select reference 2, not reference 1');
el('take-reference-card').click();
assert.equal(el('reference-preview').src, 'first-reference.png');
assert.match(el('notices').textContent, /Queue is busy/);
assert.equal(el('notices').hidden, false);
el('video').files = [new File(['video bytes'], 'source.webm')];
el('reference').files = [new File(['image bytes'], 'character.png')];
el('video').events.change();
// Explicit metadata: no fake production duration default.
Object.assign(el('source-preview'), {currentSrc: el('source-preview').src, duration: 8, videoWidth: 1280, videoHeight: 720});
el('source-preview').events.loadedmetadata();
el('add-second-reference').click();
el('reference-2').files = [new File(['second image bytes'], 'second.png')];
el('reference-2').events.change();
el('edit').value = '  original\n directions  ';
el('description').value = 'closed description must not be sent';
const inFlight = el('form').events.submit({preventDefault() {}});
await settle();
const assertFrozenReferences = () => {
  const epoch = controllerTake?.epoch, timer = controllerTake?.pollTimer;
  for (const field of ['video', 'reference', 'reference-2', 'seed', 'add-second-reference', 'remove-reference'])
    assert.equal(el(field).disabled, true, `${field} must be frozen while submitting/tracking`);
  el('reference-2').events.change();
  if (controllerTake) assert.equal(store.get('opengenjutsu.h3.current-job'), id, 'changing reference 2 cannot abandon queued/running tracking');
  for (const button of ['add-second-reference', 'remove-reference']) el(button).events.click();
  for (const field of ['video', 'reference']) el(field).events.change();
  assert.equal(el('second-reference').hidden, false);
  assert.equal(el('take-reference-2-card').hidden, false, 'locking a field must not hide the second chain card');
  assert.equal(el('reference').files[0].name, 'character.png');
  assert.equal(el('reference-2').files[0].name, 'second.png');
  assert.equal(el('run-overlay').hidden, false, 'reference events cannot reset an active take');
  assert.equal(controllerTake?.epoch, epoch); assert.equal(controllerTake?.pollTimer, timer);
};
assertFrozenReferences();
assert.equal(submitted.has('edit_prompt'), false);
assert.equal(submitted.has(el('description').name), false);
assert.equal(submitted.get('seed'), '302929098223082');
assert.equal(submitted.has('clip_start_seconds'), false); assert.equal(submitted.has('clip_end_seconds'), false);
assert.deepEqual(submitted.getAll('reference_images').map(file => file.name), ['character.png', 'second.png']);
releaseSubmit(response({job_id: id}, 202)); await inFlight; await settle();
assert.equal(store.get('opengenjutsu.h3.current-job'), id);
assertFrozenReferences();
handler = () => response({...base, status: 'running', finished: null});
await controllerTake.poll(controllerTake.epoch); assertFrozenReferences();
handler = url => response(url.endsWith('/capsule') ? capsule : url === '/api/h3/readiness' ? {ready} : {...base, status: 'done'});
await controllerTake.poll(controllerTake.epoch);
assert.equal(el('reference-2').disabled, false, 'done unlocks the visible second reference');
el('add-second-reference').click();
assert.equal(el('second-reference').hidden, true); assert.equal(el('reference-2').disabled, true);
assert.equal(el('reference-2').files.length, 0); assert.equal(el('take-reference-2-card').hidden, true);
el('video').events.change();
el('directions').open = true;
el('directions').events.toggle();
el('description').value = '  a tall woman  ';
handler = (url, opts) => {
  if (url === '/api/h3/readiness') return response({ready});
  if (url === '/api/h3/jobs') { submitted = opts.body; return response({job_id: child}, 202); }
  return response({...base, id: child, status: 'error', error: 'Test failure'});
};
await el('form').events.submit({preventDefault() {}});
await settle();
assert.equal(submitted.get('edit_prompt'), '  original\n directions  ');
assert.equal(submitted.get(el('description').name), '  a tall woman  ');
assert.equal(submitted.getAll('reference_images').length, 1); assert.equal(el('reference-2').disabled, true);
el('add-second-reference').click(); assert.equal(el('reference-2').disabled, false, 'error unlocks second-reference editing');
el('remove-reference').click();
assert.equal(el('reference').files.length, 0); assert.equal(el('second-reference').hidden, true); assert.equal(el('reference-2').disabled, true);
el('reference').files = [new File(['image bytes'], 'character.png')]; el('reference').events.change();
assert.equal(el('submit').disabled, false);
handler = (url, opts) => {
  if (url === '/api/h3/readiness') return response({ready});
  if (url === '/api/h3/jobs') return response({detail: 'The Comfy readiness probe timed out. Retry; no generation job has been submitted.'}, 503);
  return response({...base, id: child, status: 'error', error: 'Test failure'});
};
const count = calls.filter(([url]) => url === '/api/h3/jobs').length;
await el('form').events.submit({preventDefault() {}});
await settle();
assert.equal(calls.filter(([url]) => url === '/api/h3/jobs').length, count + 1);
assert.match(toasts.at(-1)[1], /timed out/);
const {checkSourceClipStudio} = await import('./h3_source_clip_studio.mjs');
await checkSourceClipStudio({el, calls, response, settle, File, id, child, base, capsule, setHandler: fn => { handler = fn; }, getTake: () => controllerTake});
console.log('H3 UI contract checks passed: exact multipart, source clip validation/preview, input freeze, done/error editing, advisory readiness, resume, replay, HTTP failures.');
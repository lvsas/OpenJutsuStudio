// Dependency-free DOM/HTTP fakes: contract tests, not real backend/GPU evidence.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {File} from 'node:buffer';
const html = readFileSync(new URL('../src/templates/h3.html', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'DIV') {
    Object.assign(this, {tagName: tag, hidden: false, disabled: false, open: false,
      textContent: '', value: '', files: [], events: {}, attrs: {}, children: [], validity: '', style: {},
      classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }}});
  }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return name === 'src' ? this.src || null : this.attrs[name] || null; }
  removeAttribute(name) { if (name === 'src') this.src = ''; else delete this.attrs[name]; }
  append(node) { this.children.push(node); }
  replaceChildren() { this.children = []; }
  get childElementCount() { return this.children.length; }
  pause() {}
  load() {}
  click() { return this.events.click?.(); }
  setCustomValidity(value) { this.validity = value; }
  closest() { return elements.get('h3-advanced'); }
}
const elements = new Map();
for (const match of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
  const element = new Element(match[1].toUpperCase());
  element.hidden = /\bhidden\b/.test(match[2]);
  element.disabled = /\bdisabled\b/.test(match[2]);
  element.value = match[2].match(/\bvalue="([^"]*)"/)?.[1] || '';
  elements.set(match[3], element);
}
elements.set('h3-advanced', new Element('DETAILS'));
// Structural parity with LTX: the source summary follows the frame, and the
// capsule lives inside the result actions rather than beside them.
// The capsule cards carry the media, exactly as the LTX cards do.
for (const kind of ['source', 'reference', 'result']) {
  assert.ok(html.includes(`id="h3-take-${kind}-preview"`), `capsule card ${kind} needs media`);
}
const frameAt = html.indexOf('class="stage-frame"');
const resultActionsAt = html.indexOf('id="h3-result-actions"');
assert.ok(html.indexOf('id="h3-source-summary"') > frameAt, 'source summary must follow the frame');
assert.ok(html.indexOf('id="h3-take-story"') > resultActionsAt, 'capsule must sit inside result actions');
const el = id => elements.get(`h3-${id}`);
globalThis.document = {getElementById: id => elements.get(id), createElement: tag => new Element(tag.toUpperCase())};
const toasts = [];
globalThis.window = {addEventListener() {}};
globalThis.window.OpenGenjutsuStudio = {showToast: (region, message, type) => toasts.push([region && region.id, message, type])};
// The real shared progress renderer, exercised with the H3 id prefix.
await import('../src/static/studio-progress.js');
const store = new Map();
globalThis.localStorage = {getItem: key => store.get(key), setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)};
const tasks = new Map();
let taskId = 0;
globalThis.setTimeout = (fn, ms) => { tasks.set(++taskId, {fn, ms}); return taskId; };
globalThis.clearTimeout = id => tasks.delete(id);
globalThis.setInterval = () => 0;
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
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
const base = {id, engine: 'minimax-h3', created: 1000, started: 1010, finished: 1070};
const capsule = {job_id: id, engine: 'minimax-h3', recipe: {original: '<img onerror=bad>'}};
let job = {...base, status: 'queued', started: null, finished: null};
handler = url => response(url.endsWith('/capsule') ? capsule : job);
const take = new H3Take(() => {}, async () => true);
take.ready = true;
take.watch(id);
await settle();
assert.equal(take.active, true);
// The shared renderer drives the overlay through the H3 id prefix.
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
// Like LTX: a finished take is not restored by a later refresh.
assert.equal(store.has('opengenjutsu.h3.current-job'), false);
assert.match(el('run-title').textContent, /Your swap is ready/);
assert.equal(el('result-preview').src, `/api/jobs/${id}/result`);
assert.equal(el('result-actions').hidden, false);
assert.match(el('capsule-manifest').textContent, /<img onerror=bad>/);
assert.equal(el('replay').disabled, false);
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
// Import the actual form controller and test exact multipart values and fail-closed readiness.
const NativeFormData = globalThis.FormData;
globalThis.FormData = class extends NativeFormData {
  constructor(form) {
    super();
    if (form) for (const [field, name] of [['video', 'video'], ['reference', 'reference_image'], ['edit', 'edit_prompt'], ['description', 'character_description'], ['seed', 'seed']]) {
      if (!el(field).disabled) this.append(name, el(field).files[0] || el(field).value);
    }
  }
};
el('form').reportValidity = () => !el('seed').validity && !!el('video').files[0] && !!el('reference').files[0];
let ready = true, submitted;
handler = (url, opts) => {
  if (url === '/api/h3/readiness') return response({ready, warnings: ['Queue is busy; waiting is not inference.']});
  if (url === '/api/h3/jobs') { submitted = opts.body; return response({job_id: id}, 202); }
  return response({...base, status: 'queued'});
};
await import('../src/static/h3-studio.js');
await settle();
assert.equal(el('submit').disabled, true);
assert.equal(el('readiness').textContent, 'Studio ready');
// Warnings land in the panel notice line, exactly as in the LTX studio.
assert.match(el('notices').textContent, /Queue is busy/);
assert.equal(el('notices').hidden, false);
el('video').files = [new File(['video bytes'], 'source.webm')];
el('reference').files = [new File(['image bytes'], 'character.png')];
el('video').events.change();
el('edit').value = '  original\n directions  ';
await el('form').events.submit({preventDefault() {}});
await settle();
assert.equal(submitted.has('edit_prompt'), false);
assert.equal(submitted.get('seed'), '302929098223082');
assert.equal(submitted.get('reference_image').name, 'character.png');
handler = url => response(url === '/api/h3/readiness' ? {ready} : {...base, status: 'done'});
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
// The user's character description reaches the frozen prompt verbatim, untrimmed.
assert.equal(submitted.get('character_description'), '  a tall woman  ');
// A false-negative readiness must never lock a valid submission: readiness is
// advisory and the server is the authoritative gate.
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
console.log('H3 UI contract checks passed: form, exact prompt, description, advisory readiness, queue, terminal states, resume, replay, HTTP failures.');
// Dependency-free DOM/HTTP fakes: contract tests, not real backend/GPU evidence.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {File} from 'node:buffer';
const html = readFileSync(new URL('../src/templates/h3.html', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'DIV') {
    Object.assign(this, {tagName: tag, hidden: false, disabled: false, open: false,
      textContent: '', value: '', files: [], events: {}, attrs: {}, children: [], validity: ''});
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
const el = id => elements.get(`h3-${id}`);
globalThis.document = {getElementById: id => elements.get(id), createElement: tag => new Element(tag.toUpperCase())};
globalThis.window = {addEventListener() {}};
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
assert.equal(el('state').textContent, 'queued');
assert.match(el('timer').textContent, /Queue wait:/);
assert.equal(store.get('opengenjutsu.h3.current-job'), id);
assert.equal(el('reference-preview').src, `/api/h3/jobs/${id}/reference`);
job = {...base, status: 'running', finished: null, step: 'h3_assemble'};
await take.poll(take.epoch);
assert.match(el('stage').textContent, /Assembling/);
job = {...base, status: 'done', step: 'done'};
await take.poll(take.epoch);
assert.equal(take.active, false);
assert.equal(el('timer').textContent, 'Elapsed: 1m 0s');
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
assert.equal(el('status').textContent, 'Input decode failed');
assert.equal(el('result-actions').hidden, true);
handler = () => { throw Error('offline'); };
take.watch(id);
await settle();
assert.equal(take.active, true); // Disconnection is not a terminal job state.
assert.match(el('status').textContent, /retry status/);
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
    if (form) for (const [field, name] of [['video', 'video'], ['reference', 'reference_image'], ['edit', 'edit_prompt'], ['seed', 'seed']]) {
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
assert.match(el('readiness-notes').children[0].textContent, /Queue is busy/);
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
await el('retry').click();
await settle();
el('video').events.change();
el('directions').open = true;
el('directions').events.toggle();
handler = (url, opts) => {
  if (url === '/api/h3/readiness') return response({ready});
  if (url === '/api/h3/jobs') { submitted = opts.body; return response({job_id: child}, 202); }
  return response({...base, id: child, status: 'error', error: 'Test failure'});
};
await el('form').events.submit({preventDefault() {}});
await settle();
assert.equal(submitted.get('edit_prompt'), '  original\n directions  ');
ready = false;
await el('retry').click();
await settle();
assert.match(el('readiness').textContent, /not ready/);
// A false-negative readiness must not lock a valid submission: the server is the authoritative gate.
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
assert.match(el('status').textContent, /timed out/);
console.log('H3 UI contract checks passed: form, exact prompt, advisory readiness, queue, terminal states, resume, replay, HTTP failures.');

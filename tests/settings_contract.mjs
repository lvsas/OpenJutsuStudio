import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const source = readFileSync(new URL('../src/static/settings.js', import.meta.url), 'utf8');
class Element {
  value = ''; checked = false; disabled = false; hidden = false; textContent = ''; children = []; listeners = {};
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async fire(type) { await Promise.all((this.listeners[type] || []).map(fn => fn({preventDefault() {}}))); }
  setAttribute(name, value) { this[name] = value; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  set innerHTML(_) { throw Error('Unsafe HTML rendering'); }
}
const saved = {revision: 3, base_url: 'https://compute.example/api', api_key_configured: true, source: 'saved', mode: 'api-v2'};
const engine = status => ({status, missing_nodes: [], missing_models: [], issues: [], warnings: []});
const result = {connected: true, ready: true, mode: 'api-v2', issues: [], warnings: [], engines: {ltx: engine('ready'), h3: engine('ready')}};
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness({form = true, search = ''} = {}) {
  const ids = ['settings-form', 'compute-url', 'compute-key', 'clear-key', 'key-status', 'settings-source', 'settings-status', 'test-status', 'test-results', 'test-connection', 'save-settings'];
  const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
  if (!form) delete nodes['settings-form'];
  const links = ['/', '/h3', '/characters', '/timeline', '/settings'].map(href => Object.assign(new Element(), {href}));
  const requests = [], events = {};
  const document = {readyState: 'complete', getElementById: id => nodes[id] || null,
    querySelectorAll: () => links, createElement: () => new Element()};
  const location = {href: 'https://studio.example/settings' + search, search, origin: 'https://studio.example', pathname: '/settings'};
  const window = {addEventListener: (name, fn) => { events[name] = fn; }};
  const fetch = (url, options = {}) => new Promise((resolve, reject) => {
    requests.push({url, options, reject, reply(data, status = 200) { resolve({ok: status < 400, status, json: async () => data}); }});
  });
  const storage = new Proxy({}, {get() { throw Error('Settings must not access storage'); }});
  vm.runInNewContext(source, {document, window, location, URL, URLSearchParams, fetch, localStorage: storage, sessionStorage: storage, console: {log() { throw Error('No logging'); }}});
  const text = node => node.textContent + node.children.map(text).join('');
  return {nodes, links, requests, window, events, text, async load() { requests[0].reply(saved); await tick(); },
    async edit(id, value) { nodes[id].value = value; await nodes[id].fire('input'); },
    test() { return nodes['test-connection'].fire('click'); }, save() { return nodes['settings-form'].fire('submit'); }};
}
function body(request) { return JSON.parse(request.options.body); }

test('navigation only reads settings; password stays blank and write-only', async () => {
  const h = harness(); assert.equal(h.requests.length, 1); assert.equal(h.requests[0].url, '/api/settings/compute');
  assert.equal(h.requests[0].options.method || 'GET', 'GET');
  h.requests[0].reply({...saved, api_key: 'MUST_NOT_ECHO'}); await tick();
  assert.equal(h.nodes['compute-key'].value, ''); assert.equal(h.nodes['compute-url'].value, saved.base_url);
  assert.match(h.nodes['key-status'].textContent, /configured/i); assert.ok(!h.text(h.nodes['settings-form']).includes('MUST_NOT_ECHO'));
});
test('typing never sends; explicit test never writes and renders text safely', async () => {
  const h = harness(); await h.load(); await h.edit('compute-key', 'secret-test');
  assert.equal(h.requests.length, 1); const pending = h.test(); assert.equal(h.requests.length, 2);
  const req = h.requests[1]; assert.equal(req.url, '/api/settings/compute/test'); assert.equal(req.options.method, 'POST');
  assert.deepEqual(body(req), {base_url: saved.base_url, api_key: 'secret-test'});
  assert.ok(h.nodes['test-connection'].disabled && h.nodes['save-settings'].disabled);
  h.requests[1].reply({...result, warnings: ['<img src=x onerror=alert(1)>', 'secret-test'], engines: {...result.engines,
    h3: {...engine('missing'), missing_nodes: ['H3Node'], missing_models: ['model.safetensors']}}}); await pending;
  const text = h.text(h.nodes['test-results']); assert.match(text, /<img/); assert.match(text, /H3Node/); assert.match(text, /model.safetensors/);
  assert.ok(!text.includes('secret-test')); assert.doesNotMatch(h.nodes['test-status'].textContent, /^Ready/);
  assert.equal(h.nodes['compute-key'].value, 'secret-test'); assert.equal(h.requests.length, 2);
});
test('save sends revision and clears the input only after success, without a target test', async () => {
  const h = harness(); await h.load(); await h.edit('compute-key', 'secret-save');
  const pending = h.save(); assert.deepEqual(body(h.requests[1]), {revision: 3, base_url: saved.base_url, api_key: 'secret-save'});
  assert.equal(h.requests[1].options.method, 'PUT'); h.requests[1].reply({...saved, revision: 4, api_key: 'secret-save'}); await pending;
  assert.equal(h.nodes['compute-key'].value, ''); assert.equal(h.requests.length, 2); assert.match(h.nodes['settings-status'].textContent, /saved/i);
  assert.ok(!h.text(h.nodes['settings-form']).includes('secret-save'));
});
test('blank key omitted; remove saved key is explicit and wins over typed input', async () => {
  const h = harness(); await h.load(); let pending = h.test(); assert.deepEqual(body(h.requests[1]), {base_url: saved.base_url});
  h.requests[1].reply(result); await pending; await h.edit('compute-key', 'discard-me');
  h.nodes['clear-key'].checked = true; await h.nodes['clear-key'].fire('change'); pending = h.save();
  assert.deepEqual(body(h.requests[2]), {revision: 3, base_url: saved.base_url, clear_api_key: true});
  h.requests[2].reply({...saved, revision: 4, api_key_configured: false}); await pending;
  assert.equal(h.nodes['clear-key'].checked, false); assert.equal(h.nodes['compute-key'].value, '');
});
test('changing URL never copies a configured key to the new destination', async () => {
  const h = harness(); await h.load(); await h.edit('compute-url', 'https://new.example/api');
  const pending = h.test(); assert.deepEqual(body(h.requests[1]), {base_url: 'https://new.example/api'});
  h.requests[1].reply(result); await pending;
});
test('test becomes obsolete on edit and stale responses cannot mark ready', async () => {
  const h = harness(); await h.load(); const pending = h.test(); await h.edit('compute-url', 'https://new.example/api');
  h.requests[1].reply(result); await pending; assert.match(h.nodes['test-status'].textContent, /obsolete/i); assert.ok(h.nodes['test-results'].hidden);
  const again = h.test(); h.requests[2].reply(result); await again; assert.match(h.nodes['test-status'].textContent, /^Ready/);
  await h.edit('compute-key', 'new-secret'); assert.match(h.nodes['test-status'].textContent, /obsolete/i); assert.ok(h.nodes['test-results'].hidden);
});
test('unknown engine is never declared ready', async () => {
  const h = harness(); await h.load(); const pending = h.test();
  h.requests[1].reply({...result, engines: {...result.engines, h3: engine('unknown')}}); await pending;
  assert.doesNotMatch(h.nodes['test-status'].textContent, /^Ready/); assert.match(h.text(h.nodes['test-results']), /unknown/i);
});
test('409 does not retry or replace edits; errors never echo response or credential', async () => {
  const h = harness(); await h.load(); await h.edit('compute-key', 'secret-conflict'); const pending = h.save();
  h.requests[1].reply({detail: 'secret-conflict /private/path'}, 409); await pending;
  assert.equal(h.requests.length, 2); assert.equal(h.nodes['compute-key'].value, 'secret-conflict');
  assert.match(h.nodes['settings-status'].textContent, /conflict|processing/i); assert.ok(!h.nodes['settings-status'].textContent.includes('secret-conflict'));
  assert.ok(!h.nodes['save-settings'].disabled);
});
test('stale save preserves newer edits but advances revision for the next explicit save', async () => {
  const h = harness(); await h.load(); await h.edit('compute-key', 'first-secret'); const pending = h.save();
  await h.edit('compute-key', 'second-secret'); h.requests[1].reply({...saved, revision: 4}); await pending;
  assert.equal(h.nodes['compute-key'].value, 'second-secret'); assert.match(h.nodes['settings-status'].textContent, /newer edits/i);
  const next = h.save(); assert.equal(body(h.requests[2]).revision, 4); h.requests[2].reply({...saved, revision: 5}); await next;
});
test('network and validation errors preserve draft and release request lock', async () => {
  for (const status of [403, 422, 500, null]) {
    const h = harness(); await h.load(); await h.edit('compute-key', 'keep-me'); const pending = h.test();
    if (status) h.requests[1].reply({detail: 'keep-me'}, status); else h.requests[1].reject(Error('keep-me'));
    await pending; assert.equal(h.nodes['compute-key'].value, 'keep-me'); assert.ok(!h.nodes['test-connection'].disabled);
    assert.ok(!h.nodes['settings-status'].textContent.includes('keep-me'));
  }
});
test('duplicate actions are ignored while busy', async () => {
  const h = harness(); await h.load(); const pending = h.test(); await h.test(); await h.save(); assert.equal(h.requests.length, 2);
  h.requests[1].reply(result); await pending;
});
test('navigation preserves valid project context without creating a project or loading settings elsewhere', async () => {
  const id = 'a'.repeat(32), h = harness({form: false, search: '?project_id=' + id});
  assert.equal(h.requests.length, 0); assert.ok(h.links.every(link => new URL(link.href, 'https://studio.example').searchParams.get('project_id') === id));
  h.window.OpenGenjutsuProject = {id: () => 'b'.repeat(32)}; h.events['opengenjutsu:project-context']();
  assert.ok(h.links.every(link => new URL(link.href, 'https://studio.example').searchParams.get('project_id') === 'b'.repeat(32)));
  const invalid = harness({form: false, search: '?project_id=bad'}); assert.ok(invalid.links.every(link => !link.href.includes('project_id')));
});

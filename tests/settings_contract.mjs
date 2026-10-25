import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const source = readFileSync(new URL('../src/static/settings.js', import.meta.url), 'utf8');
class Element {
  value = ''; checked = false; disabled = false; hidden = false; textContent = ''; children = []; listeners = {};
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async fire(type) { await Promise.all((this.listeners[type] || []).map(fn => fn({target: this, preventDefault() {}}))); }
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
  const ids = ['settings-form', 'compute-url', 'compute-key', 'clear-key', 'key-status', 'settings-source', 'settings-status', 'test-status', 'test-results', 'test-connection', 'save-settings', 'models-settings', 'model-fields', 'models-status', 'model-inventory-status', 'reset-models'];
  const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
  if (!form) delete nodes['settings-form'];
  const links = ['/', '/h3', '/characters', '/timeline', '/settings'].map(href => Object.assign(new Element(), {href}));
  const requests = [], events = {}, created = [];
  const document = {readyState: 'complete', getElementById: id => nodes[id] || created.find(node => node.id === id) || null,
    querySelectorAll: () => links, createElement: tag => { const node = new Element(); node.tagName = tag; created.push(node); return node; }};
  const location = {href: 'https://studio.example/settings' + search, search, origin: 'https://studio.example', pathname: '/settings'};
  const window = {addEventListener: (name, fn) => { events[name] = fn; }};
  const fetch = (url, options = {}) => new Promise((resolve, reject) => {
    requests.push({url, options, reject, reply(data, status = 200) { resolve({ok: status < 400, status, json: async () => data}); }});
  });
  const storage = new Proxy({}, {get() { throw Error('Settings must not access storage'); }});
  vm.runInNewContext(source, {document, window, location, URL, URLSearchParams, fetch, localStorage: storage, sessionStorage: storage, console: {log() { throw Error('No logging'); }}});
  const text = node => node.textContent + node.children.map(text).join('');
  const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
  const model = role => descendants(nodes['model-fields']).find(node => node.tagName === 'input' && node['data-model-role'] === role);
  const choices = role => { const field = model(role); return descendants(nodes['model-fields']).find(node => node.id === field.list).children.map(node => node.value); };
  return {nodes, links, requests, window, events, text, model, choices, descendants,
    async load(data = saved) { requests[0].reply(data); await tick(); },
    async editModel(role, value) { const field = model(role); assert.ok(field, 'model input exists: ' + role); field.value = value; await field.fire('input'); },
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

const roles = [
  {key: 'ltx_unet', label: 'LTX diffusion model', engine: 'ltx', class_type: 'UNETLoader', input: 'unet_name', default: 'LTX/default.safetensors'},
  {key: 'h3_unet', label: 'H3 diffusion model', engine: 'h3', class_type: 'UNETLoader', input: 'unet_name', default: 'H3/default.safetensors'},
  {key: 'shared_vae', label: 'Shared VAE', engine: 'shared', class_type: 'VAELoader', input: 'vae_name', default: 'shared.safetensors'},
];
const modelsSaved = {...saved, model_roles: roles, model_bindings: {h3_unet: 'H3/Renamed Model.SAFETENSORS'}};
const inventory = {status: 'verified', choices: {ltx_unet: ['Target/LTX renamed.safetensors'], h3_unet: ['H3/a.safetensors', 'H3/b.safetensors']}};

test('accepting a save may blur replaced model controls without inventing newer edits', async () => {
  const h = harness(); await h.load(modelsSaved);
  await h.editModel('h3_unet', 'H3/changed.safetensors');
  const focused = h.model('h3_unet');
  const replace = h.nodes['model-fields'].replaceChildren.bind(h.nodes['model-fields']);
  h.nodes['model-fields'].replaceChildren = (...items) => {
    // Chromium emits change when rebuilding removes the still-focused input.
    focused.fire('change'); replace(...items);
  };
  const pending = h.save();
  h.requests[1].reply({...modelsSaved, revision: 4, model_bindings: {h3_unet: 'H3/changed.safetensors'}});
  await pending;
  assert.match(h.nodes['settings-status'].textContent, /^Settings saved and activated/);
  assert.equal(h.model('h3_unet').value, 'H3/changed.safetensors');
});

test('model defaults and overrides are effective values, grouped and safely labelled without fetching on opening', async () => {
  const h = harness(); await h.load(modelsSaved);
  assert.equal(h.model('ltx_unet').value, roles[0].default);
  assert.equal(h.model('h3_unet').value, modelsSaved.model_bindings.h3_unet);
  const text = h.text(h.nodes['model-fields']);
  for (const label of ['LTX', 'H3', 'Shared', 'UNETLoader', 'unet_name', 'Shared VAE']) assert.ok(text.includes(label));
  const descendants = h.descendants(h.nodes['model-fields']);
  for (const role of roles) {
    const field = h.model(role.key);
    assert.equal(field.type, 'text');
    assert.ok(descendants.some(node => node.tagName === 'label' && node.htmlFor === field.id));
    assert.ok(field['aria-describedby']);
  }
  await h.nodes['models-settings'].fire('toggle');
  assert.equal(h.requests.length, 1);
  assert.match(h.nodes['model-inventory-status'].textContent, /unknown|not checked/i);
  const pending = h.test();
  assert.deepEqual(body(h.requests[1]).model_bindings, modelsSaved.model_bindings);
  h.requests[1].reply(result); await pending;
});

test('literal renamed filenames keep case, separators and spaces in Test and Save; defaults are omitted', async () => {
  const h = harness(); await h.load(modelsSaved);
  const literal = 'Sub Folder\\Renamed MODEL.SAFETENSORS ';
  await h.editModel('ltx_unet', literal); await h.editModel('h3_unet', roles[1].default);
  assert.equal(h.requests.length, 1);
  const probe = h.test(); assert.deepEqual(body(h.requests[1]).model_bindings, {ltx_unet: literal});
  h.requests[1].reply(result); await probe;
  const pending = h.save(); assert.deepEqual(body(h.requests[2]), {revision: 3, base_url: saved.base_url, model_bindings: {ltx_unet: literal}});
  h.requests[2].reply({...modelsSaved, revision: 4, model_bindings: {ltx_unet: literal}}); await pending;
  assert.equal(h.model('ltx_unet').value, literal); assert.equal(h.model('h3_unet').value, roles[1].default);
  assert.equal(h.requests.length, 3);
});

test('reset controls explicitly send an empty override object and never save or test by themselves', async () => {
  const h = harness(); await h.load(modelsSaved);
  const reset = h.descendants(h.nodes['model-fields']).find(node => node['data-reset-role'] === 'h3_unet');
  assert.equal(reset.type, 'button'); await reset.fire('click');
  assert.equal(h.model('h3_unet').value, roles[1].default);
  await h.editModel('ltx_unet', 'custom.safetensors'); await h.nodes['reset-models'].fire('click');
  assert.equal(h.requests.length, 1);
  const pending = h.save(); assert.deepEqual(body(h.requests[1]).model_bindings, {});
  h.requests[1].reply({...modelsSaved, revision: 4, model_bindings: {}}); await pending;
});

test('changing URL clears previous target overrides and suggestions, never restores them silently, permits new explicit names', async () => {
  const h = harness(); await h.load(modelsSaved);
  let pending = h.test(); h.requests[1].reply({...result, model_inventory: inventory}); await pending;
  await h.edit('compute-url', 'https://new.example/api');
  assert.equal(h.model('h3_unet').value, roles[1].default); assert.deepEqual(h.choices('h3_unet'), []);
  assert.match(h.nodes['models-status'].textContent, /different|changed/i);
  assert.match(h.nodes['models-status'].textContent, /clear|reset/i);
  await h.editModel('h3_unet', 'New Target/H3 renamed.safetensors');
  await h.nodes['compute-url'].fire('change');  // duplicate DOM event is not another target change
  pending = h.test(); assert.deepEqual(body(h.requests[2]), {base_url: 'https://new.example/api', model_bindings: {h3_unet: 'New Target/H3 renamed.safetensors'}});
  h.requests[2].reply(result); await pending;
  await h.edit('compute-url', saved.base_url);
  pending = h.save(); assert.deepEqual(body(h.requests[3]).model_bindings, {});
  h.requests[3].reply({...modelsSaved, revision: 4, model_bindings: {}}); await pending;
});

test('verified Test inventory only suggests exact literals, never selects or mutates the draft', async () => {
  const h = harness(); await h.load({...modelsSaved, model_inventory: inventory});
  assert.deepEqual(h.choices('h3_unet'), []); // GET cannot establish target inventory
  const pending = h.test(); h.requests[1].reply({...result, model_inventory: inventory}); await pending;
  assert.deepEqual(h.choices('h3_unet'), inventory.choices.h3_unet);
  assert.equal(h.model('h3_unet').value, modelsSaved.model_bindings.h3_unet);
  assert.match(h.nodes['model-inventory-status'].textContent, /verified/i);
  await h.editModel('h3_unet', 'Manual compatible name.safetensors');
  assert.equal(h.requests.length, 2);
  const next = h.test(); assert.equal(body(h.requests[2]).model_bindings.h3_unet, 'Manual compatible name.safetensors');
  h.requests[2].reply({...result, model_inventory: {status: 'unknown', choices: inventory.choices}}); await next;
  assert.equal(h.model('h3_unet').value, 'Manual compatible name.safetensors');
  assert.match(h.nodes['model-inventory-status'].textContent, /unknown/i);
  assert.deepEqual(h.choices('h3_unet'), []);
});

test('older response without model fields or inventory remains usable and omits optional bindings', async () => {
  const h = harness(); await h.load();
  assert.equal(h.nodes['model-fields'].children.length, 0);
  assert.match(h.nodes['models-status'].textContent, /unavailable|not available/i);
  const pending = h.test(); assert.ok(!Object.hasOwn(body(h.requests[1]), 'model_bindings'));
  h.requests[1].reply(result); await pending;
  assert.match(h.nodes['model-inventory-status'].textContent, /unknown/i);
});

test('model edits invalidate probe readiness and stale inventory cannot update suggestions', async () => {
  const h = harness(); await h.load(modelsSaved);
  const pending = h.test(); await h.editModel('h3_unet', 'newer.safetensors');
  h.requests[1].reply({...result, model_inventory: inventory}); await pending;
  assert.equal(h.model('h3_unet').value, 'newer.safetensors');
  assert.match(h.nodes['test-status'].textContent, /obsolete/i); assert.ok(h.nodes['test-results'].hidden);
  assert.deepEqual(h.choices('h3_unet'), []);
  const current = h.test(); h.requests[2].reply({...result, model_inventory: inventory}); await current;
  await h.editModel('h3_unet', 'still newer.safetensors');
  assert.match(h.nodes['test-status'].textContent, /obsolete/i); assert.ok(h.nodes['test-results'].hidden);
});

test('stale Save preserves model edits and URL reset while adopting committed revision, without retry', async () => {
  const h = harness(); await h.load(modelsSaved);
  await h.editModel('h3_unet', 'submitted.safetensors'); const pending = h.save();
  await h.edit('compute-url', 'https://other.example/api'); await h.editModel('ltx_unet', 'new target.safetensors');
  h.requests[1].reply({...modelsSaved, revision: 4, model_bindings: {h3_unet: 'submitted.safetensors'}}); await pending;
  assert.equal(h.model('h3_unet').value, roles[1].default); assert.equal(h.model('ltx_unet').value, 'new target.safetensors');
  assert.equal(h.nodes['compute-url'].value, 'https://other.example/api'); assert.equal(h.requests.length, 2);
  const next = h.save(); assert.deepEqual(body(h.requests[2]), {revision: 4, base_url: 'https://other.example/api', model_bindings: {ltx_unet: 'new target.safetensors'}});
  h.requests[2].reply({detail: 'secret should not display'}, 409); await next;
  assert.equal(h.requests.length, 3); assert.equal(h.model('ltx_unet').value, 'new target.safetensors');
});

test('model-only newer edit is not replaced by a stale Save and remains on next explicit save', async () => {
  const h = harness(); await h.load(modelsSaved);
  const pending = h.save(); await h.editModel('h3_unet', 'newer model.safetensors');
  h.requests[1].reply({...modelsSaved, revision: 4}); await pending;
  assert.equal(h.model('h3_unet').value, 'newer model.safetensors');
  const next = h.save(); assert.equal(body(h.requests[2]).model_bindings.h3_unet, 'newer model.safetensors');
  assert.equal(body(h.requests[2]).revision, 4); h.requests[2].reply({...modelsSaved, revision: 5, model_bindings: {h3_unet: 'newer model.safetensors'}}); await next;
});

test('inventory and model labels are text-only, with no credential echo in Test suggestions', async () => {
  const h = harness(); await h.load({...modelsSaved, model_roles: roles.map(role => ({...role, label: '<img onerror=bad>'}))});
  assert.match(h.text(h.nodes['model-fields']), /<img onerror=bad>/);
  await h.edit('compute-key', 'never-echo'); const pending = h.test();
  h.requests[1].reply({...result, model_inventory: {status: 'verified', choices: {h3_unet: ['never-echo', '<img onerror=bad>.safetensors']}}}); await pending;
  assert.deepEqual(h.choices('h3_unet'), ['<img onerror=bad>.safetensors']);
  assert.ok(!h.text(h.nodes['model-fields']).includes('never-echo'));
});

test('all declared defaults send explicit empty bindings, including defaults returned redundantly as overrides', async () => {
  const h = harness(); await h.load({...modelsSaved, model_bindings: Object.fromEntries(roles.map(role => [role.key, role.default]))});
  const pending = h.test(); assert.deepEqual(body(h.requests[1]).model_bindings, {});
  h.requests[1].reply(result); await pending;
});

test('editing URL before initial GET finishes never imports previous target filenames', async () => {
  const h = harness(); await h.edit('compute-url', 'https://early-new.example/api'); await h.load(modelsSaved);
  assert.equal(h.nodes['compute-url'].value, 'https://early-new.example/api');
  assert.equal(h.model('h3_unet').value, roles[1].default);
  const pending = h.save(); assert.deepEqual(body(h.requests[1]).model_bindings, {});
  h.requests[1].reply({...modelsSaved, revision: 4, base_url: 'https://early-new.example/api', model_bindings: {}}); await pending;
});

test('missing optional model fields on Save preserves known metadata and the current draft', async () => {
  const h = harness(); await h.load(modelsSaved); await h.editModel('h3_unet', 'manual.safetensors');
  const pending = h.save(); h.requests[1].reply({...saved, revision: 4}); await pending;
  assert.equal(h.model('h3_unet').value, 'manual.safetensors');
  const next = h.test(); assert.deepEqual(body(h.requests[2]).model_bindings, {h3_unet: 'manual.safetensors'});
  h.requests[2].reply(result); await next;
});

test('failed repeat Test leaves inventory unknown without mutating model draft or echoing server errors', async () => {
  const h = harness(); await h.load(modelsSaved);
  const first = h.test(); h.requests[1].reply({...result, model_inventory: inventory}); await first;
  const pending = h.test(); h.requests[2].reply({detail: 'private response'}, 500); await pending;
  assert.match(h.nodes['model-inventory-status'].textContent, /unknown/i);
  assert.deepEqual(h.choices('h3_unet'), []);
  assert.equal(h.model('h3_unet').value, modelsSaved.model_bindings.h3_unet);
  assert.doesNotMatch(h.nodes['settings-status'].textContent, /private response/);
});

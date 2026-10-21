/* Execute the shipped browser script in a small deterministic DOM, no npm packages.
 * Run: node --test tests/character_workspace.test.cjs
 * Network fixtures are test-only; no app, worker, GPU or persistent library is touched.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {webcrypto} = require('node:crypto');
const html = fs.readFileSync(path.join(__dirname, '../src/templates/character.html'), 'utf8');
const script = fs.readFileSync(path.join(__dirname, '../src/static/character.js'), 'utf8');
const A = 'a'.repeat(32), B = 'b'.repeat(32), C = 'c'.repeat(32);

class Element {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.dataset = {}; this.attributes = {}; this.hidden = false; this.value = ''; this.disabled = false; this._text = ''; }
  set innerHTML(_) { throw new Error('Unsafe DOM HTML assignment'); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(' '); }
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this._text = ''; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  addEventListener(event, listener) { (this.listeners[event] ||= []).push(listener); }
  async fire(event, extra = {}) { for (const listener of this.listeners[event] || []) await listener({preventDefault() {}, target: this, ...extra}); }
  click() { return this.fire('click'); }
  focus() {}
  querySelectorAll(selector) { return this.children.flatMap(child => [child, ...child.querySelectorAll('*')]).filter(node => selector === '*' || (selector.startsWith('.') && node.className?.split(' ').includes(selector.slice(1))) || node.tagName.toLowerCase() === selector); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
// A complete CPU-made 1×1 RGB PNG, not a signature-only stand-in.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC', 'base64');
const response = (data, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => data, text: async () => String(data), blob: async () => new Blob([PNG], {type:'image/png'})});
const deferred = () => { let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve}; };
async function flush() { for (let i = 0; i < 30; i++) await new Promise(resolve => setImmediate(resolve)); }

function boot({storage = {}, members = [], statuses = {}, fetchHook, storageThrows = false, nativeShare = false} = {}) {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element()]));
  const calls = [], timers = [], sharing = [];
  let library = members.map(entry => ({...entry}));
  const document = {querySelector: selector => elements.get(selector.slice(1)) || null, createElement: tag => new Element(tag)};
  elements.get('mode').value = 'portrait'; elements.get('upsampler').value = 'on';
  const localStorage = {getItem(key) { if (storageThrows) throw Error('denied'); return storage[key] ?? null; }, setItem(key, value) { if (storageThrows) throw Error('quota'); storage[key] = value; }, removeItem(key) { if (storageThrows) throw Error('denied'); delete storage[key]; }};
  const fetch = async (url, options = {}) => {
    calls.push({url, options});
    const override = fetchHook?.(url, options); if (override !== undefined) return override;
    if (url === '/api/characters/readiness') return response({ready:true, issues:[]});
    if (url === '/api/characters/library') return response({characters: library});
    if (url.startsWith('/api/characters/library/')) {
      const id = url.split('/').at(-1);
      if (options.method === 'DELETE') library = library.filter(entry => entry.job_id !== id);
      if (options.method === 'POST') { const name = JSON.parse(options.body).name || 'Untitled character'; library = [{job_id:id, name, saved_at:1, image_url:`/api/characters/jobs/${id}/image`}, ...library.filter(entry => entry.job_id !== id)]; }
      return response({job_id:id});
    }
    if (url === '/api/characters/jobs') return response({job_id:C, status:'queued'}, 202);
    const id = url.split('/')[4];
    if (url.endsWith('/caption')) return response('<script>caption</script>');
    if (url.endsWith('/image')) return response({});
    return response({job_id:id, status: statuses[id] || 'done', engine:'flux3-klein-character'});
  };
  const navigator = nativeShare ? {canShare: ({files}) => files[0].type === 'image/png', share: data => {sharing.push(data); return Promise.resolve();}} : {};
  const context = vm.createContext({document, localStorage, fetch, crypto:webcrypto, navigator, File, Blob, URL, console, Uint32Array, Uint8Array, setTimeout: callback => {timers.push(callback); return timers.length;}, clearTimeout() {}});
  vm.runInContext(script, context, {filename:'character.js'});
  return {elements, storage, calls, timers, sharing, get library() {return library;}};
}
const member = (id, name = 'Saved person') => ({job_id:id, name, saved_at:1, image_url:`/api/characters/jobs/${id}/image`});

test('one cached result survives pending work, legacy attempts migrate without auto-save', async () => {
  const app = boot({storage:{'opengenjutsu.characters.jobs':JSON.stringify([A, B]), 'opengenjutsu.characters.active':A}, statuses:{[B]:'running'}});
  await flush();
  assert.equal(app.elements.get('active-image').src, `/api/characters/jobs/${A}/image`);
  assert.equal(app.elements.get('active-result').hidden, false);
  assert.deepEqual(JSON.parse(app.storage['opengenjutsu.characters.attempts']), [A, B]);
  assert.equal(app.calls.filter(call => call.options.method === 'POST').length, 0);
  await app.elements.get('character-form').fire('submit'); await flush();
  assert.equal(app.elements.get('active-image').src, `/api/characters/jobs/${A}/image`);
  assert.equal(app.elements.get('generate').disabled, false);
});

test('saved library is server authoritative; keep and remove are verified via GET', async () => {
  const app = boot({storage:{'opengenjutsu.characters.jobs':JSON.stringify([A])}}); await flush();
  app.elements.get('character-name').value = '<img src=x onerror=alert(1)>';
  await app.elements.get('keep-character').click(); await flush();
  assert.equal(app.library.length, 1);
  assert.match(app.elements.get('library-list').textContent, /<img src=x onerror=alert\(1\)>/);
  assert.ok(app.calls.some((call, index) => call.options.method === 'POST' && app.calls[index + 1]?.url === '/api/characters/library'));
  assert.equal(app.elements.get('use-character').hidden, false);
  await app.elements.get('clear-jobs').click(); await flush();
  assert.equal(app.library.length, 1); assert.equal(app.elements.get('active-result').hidden, false);
  await app.elements.get('remove-character').click(); await flush();
  assert.equal(app.library.length, 0);
  assert.ok(app.calls.some((call, index) => call.options.method === 'DELETE' && app.calls[index + 1]?.url === '/api/characters/library'));
  assert.ok(!app.calls.some(call => /cancel|\/delete|\/media/.test(call.url)));
});

test('discard stops stale polling response from resurrecting a removed attempt', async () => {
  const waiting = deferred();
  const app = boot({storage:{'opengenjutsu.characters.jobs':JSON.stringify([B])}, fetchHook: url => url === `/api/characters/jobs/${B}` ? waiting.promise : undefined});
  await flush(); await app.elements.get('clear-jobs').click();
  waiting.resolve(response({job_id:B,status:'done'})); await flush();
  assert.equal(app.elements.get('active-result').hidden, true);
  assert.equal(app.elements.get('recent-list').children.length, 0);
});

test('localStorage denial never prevents submission or server library recovery', async () => {
  const app = boot({storageThrows:true, members:[member(A)]}); await flush();
  assert.match(app.elements.get('library-list').textContent, /Saved person/);
  await app.elements.get('character-form').fire('submit'); await flush();
  assert.ok(app.calls.some(call => call.url === '/api/characters/jobs' && call.options.method === 'POST'));
  assert.equal(app.elements.get('generate').disabled, false);
  assert.match(app.elements.get('storage-notice').textContent, /refresh/i);
});

test('native share is prepared from a PNG, never publishes or shares before gesture', async () => {
  const app = boot({storage:{'opengenjutsu.characters.jobs':JSON.stringify([A])}, nativeShare:true}); await flush();
  assert.equal(app.sharing.length, 0);
  assert.equal(app.elements.get('share-character').hidden, false);
  await app.elements.get('share-character').click(); await flush();
  assert.equal(app.sharing.length, 1);
  assert.equal(app.sharing[0].files[0].type, 'image/png');
  assert.equal(app.elements.get('download-character').download, `character-${A}.png`);
  assert.equal(app.elements.get('active-caption').textContent, '<script>caption</script>');
});

test('individual discard does not resurrect after a pending response or remove a saved person', async () => {
  const waiting = deferred();
  const app = boot({members:[member(A)], storage:{'opengenjutsu.characters.jobs':JSON.stringify([A,B]), 'opengenjutsu.characters.active':A}, fetchHook: url => url === `/api/characters/jobs/${B}` ? waiting.promise : undefined});
  await flush();
  const row = app.elements.get('recent-list').children.find(row => row.dataset.job === B);
  await row.children.find(child => child.textContent === 'Discard').click();
  waiting.resolve(response({job_id:B,status:'done'})); await flush();
  assert.equal(app.elements.get('recent-list').children.some(row => row.dataset.job === B), false);
  assert.equal(app.elements.get('active-image').src, `/api/characters/jobs/${A}/image`);
  assert.equal(app.library.length, 1);
});

test('latest explicit selection wins over an older saved selection and caption response', async () => {
  const waiting = deferred(), oldCaption = deferred(); let delay = false;
  const app = boot({members:[member(A),member(B)], storage:{'opengenjutsu.characters.active':A}, fetchHook: url => {
    if (url === `/api/characters/jobs/${A}` && delay) return waiting.promise;
    if (url === `/api/characters/jobs/${A}/caption`) return oldCaption.promise;
  }});
  await flush(); delay = true;
  const first = app.elements.get('library-list').children.find(row => row.dataset.job === A).click();
  await flush();
  await app.elements.get('library-list').children.find(row => row.dataset.job === B).click(); await flush();
  waiting.resolve(response({job_id:A,status:'done'})); oldCaption.resolve(response('Old caption')); await first; await flush();
  assert.equal(app.elements.get('active-image').src, `/api/characters/jobs/${B}/image`);
  assert.notEqual(app.elements.get('active-caption').textContent, 'Old caption');
  assert.equal(app.elements.get('use-ltx').href, `/?character_id=${B}`);
  assert.equal(app.elements.get('use-h3').href, `/h3?character_id=${B}`);
  assert.equal(app.elements.get('use-timeline').href, `/timeline?character_id=${B}`);
});

for (const autoFirst of [false, true]) {
  for (const explicitResponseFirst of [false, true]) {
    test(`empty canvas preserves explicit library selection: ${autoFirst ? 'auto' : 'click'} starts first, ${explicitResponseFirst ? 'explicit' : 'auto'} responds first`, async () => {
      const explicit = deferred(), automatic = deferred();
      let backgroundRequests = 0;
      const app = boot({members:[member(A)], storage:{'opengenjutsu.characters.attempts':JSON.stringify([B])}, fetchHook: url => {
        if (url === `/api/characters/jobs/${A}`) return explicit.promise;
        if (url === `/api/characters/jobs/${B}`) {
          backgroundRequests++;
          if (backgroundRequests === 1) return response({job_id:B, status:'running'});
          if (backgroundRequests === 2) return response({job_id:B, status:'done'});
          return automatic.promise;
        }
      }});
      await flush();
      assert.equal(app.elements.get('active-result').hidden, true);
      assert.equal(app.timers.length, 1, 'the running watcher schedules its next poll');
      const completeBackground = async () => { app.timers.shift()(); await flush(); };
      const clickSaved = () => app.elements.get('library-list').children.find(row => row.dataset.job === A).click();
      let click;
      if (autoFirst) { await completeBackground(); click = clickSaved(); }
      else { click = clickSaved(); await completeBackground(); }
      await flush();
      assert.equal(app.elements.get('active-result').hidden, true, 'a deferred selection must not invent a result');
      assert.equal(app.elements.get('recent-list').children.find(row => row.dataset.job === B).dataset.state, 'done', 'background completion still renders');
      if (explicitResponseFirst) {
        explicit.resolve(response({job_id:A, status:'done'})); await click; await flush();
        automatic.resolve(response({job_id:B, status:'done'}));
      } else {
        automatic.resolve(response({job_id:B, status:'done'})); await flush();
        assert.equal(app.elements.get('active-result').hidden, true, 'background response cannot fill the canvas during explicit intent');
        assert.notEqual(app.storage['opengenjutsu.characters.active'], B, 'background response cannot persist over explicit intent');
        explicit.resolve(response({job_id:A, status:'done'})); await click;
      }
      await flush();
      assert.equal(app.elements.get('active-image').src, `/api/characters/jobs/${A}/image`);
      assert.equal(app.storage['opengenjutsu.characters.active'], A);
      assert.equal(app.elements.get('library-list').children.find(row => row.dataset.job === A).getAttribute('aria-pressed'), 'true');
      assert.equal(app.elements.get('use-timeline').href, `/timeline?character_id=${A}`);
      assert.equal(app.calls.some(call => call.options.method), false, 'selection and polling never generate or mutate the library');
    });
  }
}

test('a successful write with failed GET verification is never shown as saved', async () => {
  let listCount = 0;
  const app = boot({storage:{'opengenjutsu.characters.jobs':JSON.stringify([A])}, fetchHook: url => {
    if (url === '/api/characters/library' && ++listCount > 1) return response({detail:'offline'},503);
  }});
  await flush(); await app.elements.get('keep-character').click(); await flush();
  assert.equal(app.elements.get('saved-state').textContent, 'Not saved');
  assert.equal(app.elements.get('use-character').hidden, true);
  assert.match(app.elements.get('workspace-notice').textContent, /Could not verify/);
  assert.equal(app.elements.get('keep-character').disabled, true);
});

test('invalid cached IDs never become URLs and current attempts supersede the legacy key', async () => {
  const app = boot({storage:{'opengenjutsu.characters.attempts':JSON.stringify([A,'../../etc/passwd','<svg>',A]),'opengenjutsu.characters.jobs':JSON.stringify([B])}}); await flush();
  assert.equal(app.elements.get('recent-list').children.length,1);
  assert.ok(app.calls.every(call => !call.url.includes('passwd') && !call.url.includes('<svg>') && !call.url.includes(B)));
});

test('saved cached selection takes priority even when library restoration is slower than an attempt', async () => {
  const waiting = deferred();
  const app = boot({storage:{'opengenjutsu.characters.active':A,'opengenjutsu.characters.jobs':JSON.stringify([B])}, fetchHook: url => url === '/api/characters/library' ? waiting.promise : undefined});
  await flush(); waiting.resolve(response({characters:[member(A)]})); await flush();
  assert.equal(app.elements.get('active-image').src, `/api/characters/jobs/${A}/image`);
});

test('readiness errors, failed image loads and unsupported share keep truthful download fallback', async () => {
  const app = boot({storage:{'opengenjutsu.characters.jobs':JSON.stringify([A])}, nativeShare:true, fetchHook: url => {
    if (url === '/api/characters/readiness') return response({ready:true},503);
    if (url.endsWith('/image')) return {...response({}), blob: async () => new Blob(['not a png'],{type:'image/png'})};
  }}); await flush();
  assert.equal(app.elements.get('readiness').dataset.state,'blocked');
  assert.equal(app.elements.get('share-character').hidden,true);
  assert.equal(app.sharing.length,0);
  await app.elements.get('active-image').fire('error');
  assert.match(app.elements.get('image-state').textContent,/unavailable/);
  assert.equal(app.elements.get('download-character').href,`/api/characters/jobs/${A}/image`);
});

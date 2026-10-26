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
  focus(options) { (this.focusCalls ||= []).push(options); }
  scrollIntoView(options) { (this.scrollCalls ||= []).push(options); }
  querySelectorAll(selector) { return this.children.flatMap(child => [child, ...child.querySelectorAll('*')]).filter(node => selector === '*' || (selector.startsWith('.') && node.className?.split(' ').includes(selector.slice(1))) || node.tagName.toLowerCase() === selector); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
// A complete CPU-made 1×1 RGB PNG, not a signature-only stand-in.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC', 'base64');
const response = (data, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => data, text: async () => String(data), blob: async () => new Blob([PNG], {type:'image/png'})});
const deferred = () => { let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve}; };
async function flush() { for (let i = 0; i < 30; i++) await new Promise(resolve => setImmediate(resolve)); }

function boot({storage = {}, members = [], statuses = {}, fetchHook, storageThrows = false, nativeShare = false, search = '', project} = {}) {
  const elements = new Map([...html.matchAll(/<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)].map(([, tag, attrs, id]) => {
    const element = new Element(tag);
    element.type = attrs.match(/\btype="([^"]+)"/)?.[1] || '';
    element.hidden = /\bhidden\b/.test(attrs);
    element.checked = /\bchecked\b/.test(attrs);
    return [id, element];
  }));
  const calls = [], timers = [], sharing = [];
  let library = members.map(entry => ({...entry}));
  const document = {querySelector: selector => elements.get(selector.slice(1)) || null, createElement: tag => new Element(tag)};
  for(const id of ['mode','upsampler']) {
    const options=html.match(new RegExp(`<select id="${id}"[^>]*>([\\s\\S]*?)</select>`))[1];
    const selected=[...options.matchAll(/<option value="([^"]+)"([^>]*)>/g)];
    elements.get(id).value=(selected.find(([, ,attrs])=>/\bselected\b/.test(attrs)) || selected[0])[1];
  }
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
  const location={href:'http://studio.test/characters'+search,pathname:'/characters',search};
  const history={replaceState(_state,_title,value){const next=new URL(value,location.href);location.href=next.href;location.search=next.search;}};
  const context = vm.createContext({document, localStorage, fetch, crypto:webcrypto, navigator, File, Blob, URL, URLSearchParams, location, history, OpenGenjutsuProject:project ? {storageKey:key=>key,...project} : undefined, console, Uint32Array, Uint8Array, setTimeout: callback => {timers.push(callback); return timers.length;}, clearTimeout() {}});
  vm.runInContext(script, context, {filename:'character.js'});
  return {elements, storage, calls, timers, sharing, location, get library() {return library;}};
}
test('face refinement is explicit, unchecked by default and submits literal booleans', async () => {
  assert.match(html, /<input[^>]*id="face-refine"[^>]*name="face_refine"[^>]*>/);
  const control = html.match(/<input[^>]*id="face-refine"[^>]*>/)[0];
  assert.match(control, /type="checkbox"/); assert.doesNotMatch(control, /\bchecked\b/);
  assert.ok(html.indexOf('id="face-refine"') > html.indexOf('id="more-control"'));
  assert.ok(html.indexOf('id="face-refine"') < html.indexOf('id="axis-picker"'));
  assert.match(html, /Refine face \(extra pass\)/);
  const app = boot(); await flush();
  assert.equal(app.calls.some(c=>c.options.method==='POST'), false);
  await app.elements.get('character-form').fire('submit'); await flush();
  app.elements.get('face-refine').checked = true;
  await app.elements.get('character-form').fire('submit'); await flush();
  const payloads=app.calls.filter(c=>c.url==='/api/characters/jobs' && c.options.method==='POST').map(c=>JSON.parse(c.options.body));
  assert.deepEqual(payloads.map(p=>p.face_refine), [false,true]);
});

test('original comparison is secondary, status-gated and follows the selected completed job', async () => {
  assert.match(html, /<details[^>]*id="more-details"[\s\S]*id="inspect-base"[\s\S]*?<\/details>/);
  const app=boot({members:[member(A),member(B)], storage:{'opengenjutsu.characters.active':A}, fetchHook:url=>{
    if(url===`/api/characters/jobs/${A}`)return response({job_id:A,status:'done',face_refine:true});
    if(url===`/api/characters/jobs/${B}`)return response({job_id:B,status:'done',face_refine:false});
  }}); await flush();
  const link=app.elements.get('inspect-base');
  assert.equal(link.hidden,false); assert.equal(link.href,`/api/characters/jobs/${A}/base-image`);
  assert.match(html, /id="inspect-base"[^>]*>View original<\/a>/);
  await app.elements.get('active-image').fire('load');
  assert.match(app.elements.get('image-state').textContent,/face-refined/);
  await app.elements.get('library-list').children.find(row=>row.dataset.job===B).click(); await flush();
  assert.equal(link.hidden,true); assert.equal(link.href,'');
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${B}/image`);
  assert.equal(app.calls.some(c=>c.url.endsWith('/base-image')||c.options.method==='POST'),false,'comparison never fetches or generates automatically');
  for(const flag of [undefined,'true',1]){
    const legacy=boot({members:[member(A)],storage:{'opengenjutsu.characters.active':A},fetchHook:url=>url===`/api/characters/jobs/${A}`?response({job_id:A,status:'done',face_refine:flag}):undefined});
    await flush(); assert.equal(legacy.elements.get('inspect-base').hidden,true);
  }
});

const member = (id, name = 'Saved person') => ({job_id:id, name, saved_at:1, image_url:`/api/characters/jobs/${id}/image`});

test('editable idea and early submit precede refinements; shuffle is local person-only weird adult', async () => {
  const stack = []; let ideaAncestors;
  for (const match of html.matchAll(/<\/?(?:details|textarea)\b[^>]*>/g)) {
    if (match[0].startsWith('</details')) stack.pop();
    else if (match[0].startsWith('<details')) stack.push(match[0]);
    else if (match[0].includes('id="direction"')) ideaAncestors = [...stack];
  }
  assert.equal(ideaAncestors.length,1);
  assert.match(ideaAncestors[0],/id="idea-editor"/,'long prompt editing is optional; the short idea remains visible');
  assert.ok(html.indexOf('id="idea-summary"') < html.indexOf('id="generate"'));
  assert.ok(html.indexOf('id="generate"') < html.indexOf('id="refine-list"'));
  assert.ok(html.indexOf('id="generate"') < html.indexOf('id="more-control"'));
  const app = boot(); await flush();
  assert.equal(app.elements.get('direction').tagName, 'TEXTAREA');
  assert.equal(app.elements.get('direction').hidden, false);
  assert.equal(app.elements.get('generate').type, 'submit');
  assert.equal(app.elements.get('shuffle').type, 'button');
  const before = app.calls.length;
  for (let i = 0; i < 30; i++) {
    await app.elements.get('shuffle').click();
    const idea = app.elements.get('direction').value;
    assert.match(idea, /^An original adult (?:man|woman|non-binary person),/);
    assert.doesNotMatch(idea, /caricature|outsized head|tiny waist|spindly legs|tiny neat feet/i);
    assert.match(idea, /flat|geometric|sculptural|halo|cascade|waves/);
    assert.doesNotMatch(idea, /editorial|street.style|photograph|studio|portrait|holding|carrying/i);
  }
  assert.equal(app.calls.length, before, 'shuffle must perform zero fetches');
  assert.match(app.elements.get('refine-list').textContent, /Build.*Hair.*Face.*Clothes.*Expression/);
  const silhouette = app.elements.get('refine-list').children[0];
  await silhouette.click();
  const custom = app.elements.get('refine-options').querySelector('input');
  assert.equal(custom.maxLength, 300);
  custom.value = 'a broad triangular silhouette'; await custom.fire('change');
  assert.match(app.elements.get('refine-list').textContent, /a broad triangular silhouette/);
  assert.equal(app.elements.get('clear-axes').hidden, false);
  await app.elements.get('clear-axes').click();
  assert.equal(app.elements.get('clear-axes').hidden, true);
  app.elements.get('direction').value = 'My own original person';
  await app.elements.get('direction').fire('input');
  await app.elements.get('character-form').fire('submit'); await flush();
  const payload = JSON.parse(app.calls.find(call => call.options.method === 'POST').options.body);
  assert.equal(payload.direction, 'My own original person');
  assert.equal(payload.direction_origin, 'user_authored');
});

test('one cached result survives pending work, legacy attempts migrate without auto-save', async () => {
  const app = boot({storage:{'opengenjutsu.characters.jobs':JSON.stringify([A, B]), 'opengenjutsu.characters.active':A}, statuses:{[B]:'running',[C]:'running'}});
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
  await row.querySelector('.attempt-hide').click();
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
  assert.equal(app.elements.get('active-result').scrollCalls.length,1,'stale selection cannot reveal the old result');
  assert.equal(app.elements.get('active-result').focusCalls.length,1,'stale selection cannot steal focus');
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
      assert.equal(app.elements.get('active-result').scrollCalls.length,1,'only the winning explicit selection reveals');
      assert.equal(app.elements.get('active-result').focusCalls.length,1);
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

test('latest explicitly generated turnaround replaces the old preview quietly on completion', async () => {
  let polls=0;
  const app=boot({members:[member(A)],storage:{'opengenjutsu.characters.active':A},fetchHook:url=>url===`/api/characters/jobs/${C}`?response({job_id:C,status:++polls===1?'running':'done',mode:'turnaround'}):undefined});
  await flush();
  app.elements.get('mode').value='turnaround'; await app.elements.get('mode').fire('change');
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${A}/image`,'changing view alone does not transform a saved image');
  await app.elements.get('character-form').fire('submit'); await flush();
  assert.equal(JSON.parse(app.calls.find(c=>c.options.method==='POST').options.body).mode,'turnaround');
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${A}/image`);
  assert.match(app.elements.get('generation-state').textContent,/turnaround/i);
  app.timers.shift()(); await flush();
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${C}/image`);
  assert.match(app.elements.get('result-mode').textContent,/Turnaround/);
  assert.equal(app.elements.get('active-result').scrollCalls?.length||0,0);
  assert.equal(app.elements.get('active-result').focusCalls?.length||0,0);
});

test('a completed new generation never overwrites a later explicit choice', async () => {
  let polls=0;
  const app=boot({members:[member(A),member(B)],storage:{'opengenjutsu.characters.active':A},fetchHook:url=>url===`/api/characters/jobs/${C}`?response({job_id:C,status:++polls===1?'running':'done',mode:'full_body'}):undefined});
  await flush(); await app.elements.get('character-form').fire('submit'); await flush();
  await app.elements.get('library-list').children.find(e=>e.dataset.job===B).click(); await flush();
  app.timers.shift()(); await flush();
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${B}/image`);
  assert.match(app.elements.get('generation-state').textContent,/ready/i);
  assert.equal(app.elements.get('recent-list').children.find(e=>e.dataset.job===C).dataset.state,'done');
});

test('default idea and adjustment labels are short; tabs and adjustments never generate', async () => {
  const app=boot(); await flush(); const before=app.calls.length;
  assert.ok(app.elements.get('idea-summary').textContent.length>30);
  assert.ok(app.elements.get('idea-summary').textContent.length<220);
  await app.elements.get('refine-list').children.find(e=>e.dataset.refinement==='appearance').click();
  const chips=app.elements.get('refine-options').querySelectorAll('.chip');
  assert.ok(chips.length>=6);
  for(const chip of chips)assert.ok(chip.textContent.length<=48,chip.textContent);
  await app.elements.get('tab-saved').click();
  assert.equal(app.elements.get('recent-attempts').hidden,true);
  assert.equal(app.elements.get('saved-characters').hidden,false);
  await app.elements.get('tab-attempts').click();
  assert.equal(app.elements.get('recent-attempts').hidden,false);
  assert.equal(app.calls.length,before);
});

test('browser-hidden project attempts stay hidden after reload and a server merge', async () => {
  const storage={}; const project={jobs:()=>[{job_id:A},{job_id:B}],containsJob:()=>true};
  const app=boot({storage,project}); await flush();
  const row=app.elements.get('recent-list').children.find(e=>e.dataset.job===B);
  await row.querySelector('.attempt-hide').click(); await flush();
  const restored=boot({storage,project}); await flush();
  assert.equal(restored.elements.get('recent-list').children.some(e=>e.dataset.job===B),false);
  assert.equal(restored.elements.get('recent-list').children.some(e=>e.dataset.job===A),true);
  assert.equal(app.calls.some(c=>c.options.method),false,'hiding is not deletion or submission');
});

test('reuse idea reads the selected capsule explicitly and never generates', async () => {
  const app=boot({members:[member(A)],storage:{'opengenjutsu.characters.active':A},fetchHook:url=>url.endsWith('/capsule')?response({recipe:{schema_version:6,raw_direction:'An adult in a purple sculpted jacket.'}}):undefined});
  await flush(); assert.equal(app.calls.some(c=>c.url.endsWith('/capsule')),false);
  await app.elements.get('reuse-idea').click(); await flush();
  assert.equal(app.elements.get('direction').value,'An adult in a purple sculpted jacket.');
  assert.equal(app.elements.get('idea-editor').open,true);
  assert.equal(app.elements.get('proposal-refinements').hidden,true);
  assert.equal(generationPayloads(app).length,0);
  assert.match(app.elements.get('workspace-notice').textContent,/identity can change/);
});

test('a late reused idea cannot replace a draft edited while it loads', async () => {
  const wait=deferred();
  const app=boot({members:[member(A)],storage:{'opengenjutsu.characters.active':A},fetchHook:url=>url.endsWith('/capsule')?wait.promise:undefined});
  await flush(); const loading=app.elements.get('reuse-idea').click(); await flush();
  app.elements.get('direction').value='My newer character idea';await app.elements.get('direction').fire('input');
  wait.resolve(response({recipe:{schema_version:6,raw_direction:'An older idea.'}}));await loading;await flush();
  assert.equal(app.elements.get('direction').value,'My newer character idea');
  assert.equal(generationPayloads(app).length,0);
});

test('deep-link selection and hiding survive reload without reviving the old image', async () => {
  const storage={},project={jobs:()=>[{job_id:A},{job_id:B}],containsJob:()=>true};
  const app=boot({storage,project,search:`?job_id=${A}`});await flush();
  await app.elements.get('recent-list').children.find(e=>e.dataset.job===B).querySelector('.attempt-select').click();await flush();
  assert.equal(new URLSearchParams(app.location.search).get('job_id'),B);
  const restored=boot({storage,project,search:app.location.search});await flush();
  assert.equal(restored.elements.get('active-image').src,`/api/characters/jobs/${B}/image`);
  await restored.elements.get('recent-list').children.find(e=>e.dataset.job===B).querySelector('.attempt-hide').click();await flush();
  assert.equal(new URLSearchParams(restored.location.search).has('job_id'),false);
  const hidden=boot({storage,project,search:restored.location.search});await flush();
  assert.equal(hidden.elements.get('recent-list').children.some(e=>e.dataset.job===B),false);
});

test('refresh restores an explicit pending result without another submission', async () => {
  const storage={'opengenjutsu.characters.active':A,'opengenjutsu.characters.pending-result':C,'opengenjutsu.characters.attempts':JSON.stringify([C,A])};
  const app=boot({storage});await flush();
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${C}/image`);
  assert.equal(storage['opengenjutsu.characters.pending-result'],'');
  assert.equal(generationPayloads(app).length,0);
});

test('local shuffle explores all eighteen coherent combinations before repeating', async () => {
  const app=boot();await flush();const before=app.calls.length,ideas=[];
  for(let i=0;i<18;i++){
    ideas.push(app.elements.get('direction').value);
    if(i<17)await app.elements.get('shuffle').click();
  }
  assert.equal(new Set(ideas).size,18);
  const personas=vm.runInNewContext(script.match(/const LOOKS = (\[[\s\S]*?\n  \]);/)[1]);
  for(const look of personas)assert.equal(ideas.filter(text=>text.includes(look.role+':')).length,3);
  for(let i=1;i<ideas.length;i++){
    const previous=personas.find(look=>ideas[i-1].includes(look.role+':'));
    assert.equal(ideas[i].includes(previous.role+':'),false,'a new idea should visibly change the persona');
  }
  assert.equal(app.calls.length,before,'the variety loop remains local and free of computation');
});

const generationPayloads = app => app.calls.filter(c=>c.url==='/api/characters/jobs' && c.options.method==='POST').map(c=>JSON.parse(c.options.body));
const canonical = look => `An original adult ${look.being}, ${/^[aeiou]/i.test(look.role)?'an':'a'} ${look.role}: ${look.build}, ${look.hair}, ${look.face}, wearing ${look.outfit}, ${look.attitude}.`;

test('generated submissions carry an exact copied base snapshot; refinements stay local and separate', async () => {
  const app=boot(); await flush();
  await app.elements.get('character-form').fire('submit'); await flush();
  const base=generationPayloads(app)[0];
  assert.ok(base.direction_facts,'generated direction must carry facts, not only prose');
  assert.deepEqual(Object.keys(base.direction_facts).sort(),['being','role','build','hair','face','outfit','attitude','primary_axis'].sort());
  assert.equal(base.direction,canonical(base.direction_facts));
  assert.equal(base.direction_origin,'generated');
  assert.deepEqual(base.selections,{});
  const catalogue=vm.runInNewContext(script.match(/const LOOKS = (\[[\s\S]*?\n  \]);/)[1]);
  const wardrobes=vm.runInNewContext(script.match(/const WARDROBES = (\[[\s\S]*?\n  \]);/)[1]);
  const persona=catalogue.findIndex(look=>Object.keys(look).filter(key=>key!=='outfit').every(key=>look[key]===base.direction_facts[key]));
  assert.ok(persona>=0);
  assert.ok(wardrobes[persona].some(entry=>entry.outfit===base.direction_facts.outfit),'wardrobe must be curated for this exact persona');
  const before=app.calls.length;
  await app.elements.get('refine-list').children[0].click();
  const input=app.elements.get('refine-options').querySelector('input');
  input.value='a narrow angular silhouette'; await input.fire('change');
  assert.equal(app.calls.length,before,'local refinement cannot fetch or render');
  assert.equal(app.elements.get('direction').value,base.direction,'the canonical base is not rewritten by overrides');
  await app.elements.get('character-form').fire('submit'); await flush();
  const refined=generationPayloads(app)[1];
  assert.deepEqual(refined.direction_facts,base.direction_facts,'snapshot must stay the unmodified base tuple');
  assert.deepEqual(refined.selections,{build:'a narrow angular silhouette'});
  assert.equal(refined.direction,base.direction);
  await app.elements.get('shuffle').click();
  await app.elements.get('character-form').fire('submit'); await flush();
  const reset=generationPayloads(app)[2];
  assert.deepEqual(reset.selections,{});
  assert.equal(reset.direction_origin,'generated');
  assert.equal(reset.direction,canonical(reset.direction_facts));
  assert.equal(app.elements.get('clear-axes').hidden,true);
});

test('editing an idea clears facts and overrides, blocks stale refinement handlers and keeps output controls usable', async () => {
  const app=boot(); await flush();
  await app.elements.get('refine-list').children[0].click();
  const staleInput=app.elements.get('refine-options').querySelector('input');
  staleInput.value='an extremely broad silhouette'; await staleInput.fire('change');
  const staleButton=app.elements.get('axis-select');
  const before=app.calls.length;
  app.elements.get('direction').value='My own adult character with asymmetric short hair.';
  await app.elements.get('direction').fire('input');
  assert.equal(app.elements.get('proposal-refinements').hidden,true);
  assert.equal(app.elements.get('fine-refinements').hidden,true);
  assert.equal(app.elements.get('refine-options').children.length,0);
  assert.equal(app.elements.get('axis-options').children.length,0);
  assert.equal(app.elements.get('clear-axes').hidden,true);
  assert.match(app.elements.get('proposal-summary').textContent,/Your own idea.*Another idea restores/);
  staleInput.value='stale override'; await staleInput.fire('change'); staleButton.value='hair'; await staleButton.fire('change');
  assert.equal(app.elements.get('axis-options').children.length,0);
  for(const id of ['mode','upsampler','face-refine'])assert.equal(app.elements.get(id).disabled,false);
  app.elements.get('mode').value='full_body'; await app.elements.get('mode').fire('change');
  app.elements.get('upsampler').value='on'; app.elements.get('face-refine').checked=true;
  assert.equal(app.calls.length,before,'editing and output choices are zero-fetch');
  await app.elements.get('character-form').fire('submit'); await flush();
  const authored=generationPayloads(app)[0];
  assert.equal(authored.direction_facts,null);
  assert.equal(authored.direction_origin,'user_authored');
  assert.equal(authored.direction,'My own adult character with asymmetric short hair.');
  assert.deepEqual(authored.selections,{});
  assert.equal(authored.mode,'full_body'); assert.equal(authored.upsampler,true); assert.equal(authored.face_refine,true);
  await app.elements.get('shuffle').click();
  assert.equal(app.elements.get('proposal-refinements').hidden,false);
  assert.equal(app.elements.get('fine-refinements').hidden,false);
  await app.elements.get('refine-list').children[0].click();
  assert.ok(app.elements.get('refine-options').querySelector('input'));
});

test('a programmatically changed idea is never sent with a stale generated snapshot', async () => {
  const app=boot(); await flush();
  await app.elements.get('refine-list').children[0].click();
  const input=app.elements.get('refine-options').querySelector('input'); input.value='old override'; await input.fire('change');
  app.elements.get('direction').value='New free text without an input event';
  await app.elements.get('character-form').fire('submit'); await flush();
  const payload=generationPayloads(app)[0];
  assert.equal(payload.direction_facts,null); assert.equal(payload.direction_origin,'user_authored'); assert.deepEqual(payload.selections,{});
});

test('an explicit submission freezes its idea and facts before awaiting project creation', async () => {
  const waiting=deferred();
  const project={ensure:()=>waiting.promise, jobs:()=>[], acceptJob(){}};
  const app=boot({project}); await flush();
  const before=app.elements.get('direction').value;
  const submitted=app.elements.get('character-form').fire('submit'); await flush();
  app.elements.get('direction').value='A new draft while submitting'; await app.elements.get('direction').fire('input');
  waiting.resolve('project-id'); await submitted; await flush();
  const payload=generationPayloads(app)[0];
  assert.equal(payload.project_id,'project-id'); assert.equal(payload.direction,before);
  assert.equal(payload.direction_origin,'generated'); assert.equal(payload.direction,canonical(payload.direction_facts));
});

test('mode copy distinguishes a face-and-hair portrait, full figure and unchanged four-angle turnaround', async () => {
  const app=boot(); await flush();
  assert.match(html,/<option value="portrait">Portrait · 3:4<\/option>/);
  assert.match(html,/<option value="full_body">Full body · 3:4<\/option>/);
  assert.match(html,/<option value="turnaround">Turnaround · 16:9<\/option>/);
  assert.match(html,/id="mode-hint">[^<]*waist-up[^<]*(?:face|hairstyle)/i);
  assert.match(html,/<option value="on">[^<]*expand[^<]*rewrite[^<]*short idea/i);
  assert.match(html,/<option value="off" selected>[^<]*exact[^<]*full caption/i);
  assert.equal(app.elements.get('upsampler').value,'off','harness must use the served default');
  const before=app.calls.length;
  for(const [mode,copy] of [['portrait',/waist-up.*face.*hairstyle/i],['full_body',/full figure.*feet/i],['turnaround',/front, three-quarter, profile, back/]]) {
    app.elements.get('mode').value=mode; await app.elements.get('mode').fire('change');
    assert.match(app.elements.get('mode-hint').textContent,copy);
  }
  assert.equal(app.calls.length,before);
});

test('explicit saved and recent selections reveal and focus the canvas; restoration never does', async () => {
  const app=boot({members:[member(A)],storage:{'opengenjutsu.characters.attempts':JSON.stringify([B]),'opengenjutsu.characters.active':A}}); await flush();
  const canvas=app.elements.get('active-result');
  assert.equal(canvas.scrollCalls?.length||0,0); assert.equal(canvas.focusCalls?.length||0,0);
  const row=app.elements.get('recent-list').children.find(row=>row.dataset.job===B);
  await row.querySelector('.attempt-select').click(); await flush();
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${B}/image`);
  assert.equal(canvas.scrollCalls?.length||0,1,'explicit Choose must reveal the off-screen canvas'); assert.equal(canvas.scrollCalls[0].block,'start');
  assert.equal(canvas.focusCalls?.length||0,1,'explicit Choose must focus the result'); assert.equal(canvas.focusCalls[0].preventScroll,true);
  assert.match(html,/<article[^>]*id="active-result"[^>]*tabindex="-1"/);
  await app.elements.get('library-list').children[0].click(); await flush();
  assert.equal(canvas.scrollCalls.length,2); assert.equal(canvas.focusCalls.length,2);
  assert.equal(generationPayloads(app).length,0);
});

test('boot deep links and automatic polling completion never reveal, focus or generate', async () => {
  const project={jobs:()=>[{job_id:A}],containsJob:id=>id===A};
  const app=boot({search:`?job_id=${A}`,project}); await flush();
  assert.equal(app.elements.get('active-image').src,`/api/characters/jobs/${A}/image`);
  assert.equal(app.elements.get('active-result').scrollCalls?.length||0,0);
  assert.equal(app.elements.get('active-result').focusCalls?.length||0,0);
  let polls=0;
  const polling=boot({storage:{'opengenjutsu.characters.attempts':JSON.stringify([B])},fetchHook:url=>url===`/api/characters/jobs/${B}`?response({job_id:B,status:++polls===1?'running':'done'}):undefined}); await flush();
  polling.timers.shift()(); await flush();
  assert.equal(polling.elements.get('active-image').src,`/api/characters/jobs/${B}/image`);
  assert.equal(polling.elements.get('active-result').scrollCalls?.length||0,0);
  assert.equal(polling.elements.get('active-result').focusCalls?.length||0,0);
  assert.equal(generationPayloads(app).length+generationPayloads(polling).length,0);
});

test('remove from library is a visible management action outside every closed disclosure', async () => {
  const stack=[]; let ancestors;
  for(const match of html.matchAll(/<\/?(?:details|button)\b[^>]*>/g)) {
    if(match[0].startsWith('</details'))stack.pop();
    else if(match[0].startsWith('<details'))stack.push(match[0]);
    else if(match[0].includes('id="remove-character"'))ancestors=[...stack];
  }
  assert.deepEqual(ancestors,[],'Remove must not be hidden by More details');
  assert.match(html,/<div[^>]*id="library-management"[^>]*>[\s\S]*?id="character-name"[\s\S]*?id="keep-character"[\s\S]*?<\/div>/);
  assert.match(html,/Removing a library or project entry never deletes media/i);
  assert.match(html,/<section[^>]*id="saved-characters"[\s\S]*?id="remove-character"[\s\S]*?<\/section>/);

  const app=boot({members:[member(A)],storage:{'opengenjutsu.characters.active':A}}); await flush();
  assert.equal(app.elements.get('more-details').open,false);
  assert.equal(app.elements.get('remove-character').hidden,false);
  await app.elements.get('remove-character').click(); await flush();
  assert.equal(app.library.length,0);
  assert.ok(app.calls.some((c,i)=>c.url===`/api/characters/library/${A}` && c.options.method==='DELETE' && app.calls[i+1]?.url==='/api/characters/library'));
  assert.match(app.elements.get('workspace-notice').textContent,/media, capsule and job are retained/);
});

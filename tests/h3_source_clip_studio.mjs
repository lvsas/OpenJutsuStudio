// Exercises the imported, real h3-studio.js with the template-derived DOM harness.
import assert from 'node:assert/strict';
export async function checkSourceClipStudio({el, calls, response, settle, File, id, child, base, capsule, setHandler, getTake}) {
  const postCount = () => calls.filter(([, options]) => options.method === 'POST').length;
  const submit = () => el('form').events.submit({preventDefault() {}});
  const media = el('source-preview');
  const range = () => [el('clip-start').value, el('clip-end').value];
  const edit = (start, end) => {
    el('clip-start').value = start; el('clip-end').value = end; el('clip-end').events.input();
  };
  const metadata = (duration, url = media.src) => {
    Object.assign(media, {currentSrc: url, duration, videoWidth: 1280, videoHeight: 720});
    media.events.loadedmetadata();
  };
  const select = name => {
    el('video').files = [new File(['local video bytes'], name, {type: 'video/mp4'})];
    el('video').events.change();
  };
  const before = postCount(), plays = media.plays;
  select('long-original.mp4');
  const oldMetadata = media.listeners.get('loadedmetadata').at(-1);
  assert.equal(el('submit').disabled, true); assert.match(el('clip-status').textContent, /MP4/);
  await submit(); assert.equal(postCount(), before, 'pending metadata cannot submit');
  metadata(42);
  assert.deepEqual(range(), ['0', '15']); assert.equal(el('submit').disabled, false);
  assert.equal(el('source-clip').hidden, false);
  assert.match(el('clip-limit').textContent, /15/);
  assert.match(el('clip-summary').textContent, /Original: 42 s · Selected: 15 s/);
  assert.equal(media.plays, plays, 'import does not autoplay');
  const NativeFormData = globalThis.FormData;
  let constructed = 0;
  globalThis.FormData = class extends NativeFormData { constructor(form) { super(form); constructed++; } };
  for (const [start, end] of [['0', '15.01'], ['-1', '5'], ['5', '2'], ['0', '43'], ['', '5'], ['NaN', '5'], ['0', 'Infinity']]) {
    edit(start, end); assert.equal(el('submit').disabled, true);
    assert.ok(el('clip-status').textContent); assert.equal(el('clip-end').attrs['aria-invalid'], 'true');
    await submit(); assert.equal(postCount(), before); assert.equal(constructed, 0, 'invalid range is rejected before FormData');
  }
  edit('2', '5');
  const sourceURL = media.src;
  el('reference').events.change();
  assert.deepEqual(range(), ['2', '5']); assert.equal(media.src, sourceURL, 'reference changes reuse the original URL');
  el('seed').events.input(); el('directions').events.toggle();
  assert.deepEqual(range(), ['2', '5']);
  select('replacement.mp4'); metadata(30);
  edit('2', '5'); oldMetadata();
  assert.deepEqual(range(), ['2', '5']); assert.match(el('clip-summary').textContent, /Original: 30 s/);
  media.src = `/api/h3/jobs/${id}/source`; metadata(3);
  assert.deepEqual(range(), ['2', '5']); assert.match(el('clip-summary').textContent, /Original: 30 s/, 'saved-take metadata must not replace original duration');
  el('clip-preview').click();
  assert.equal(media.currentTime, 2); assert.equal(media.plays, plays + 1);
  assert.match(media.src, /^blob:/); assert.equal(media.hidden, false);
  metadata(30); media.currentTime = 5.1; media.events.timeupdate();
  assert.equal(media.currentTime, 5); assert.ok(media.pauses > 0); assert.equal(postCount(), before);
  let payload, release;
  setHandler((url, options) => {
    if (url === '/api/h3/jobs') { payload = options.body; return new Promise(resolve => { release = resolve; }); }
    return response({...base, id: child, status: 'queued'});
  });
  const inFlight = submit(); await settle();
  assert.deepEqual(payload.getAll('clip_start_seconds'), ['2']); assert.deepEqual(payload.getAll('clip_end_seconds'), ['5']);
  assert.equal(constructed, 1); globalThis.FormData = NativeFormData;
  const assertLocked = () => {
    for (const name of ['clip-start', 'clip-end', 'clip-preview']) assert.equal(el(name).disabled, true, name);
    edit('0', '15'); metadata(999); el('clip-preview').events.click();
    assert.deepEqual(range(), ['2', '5']); assert.match(el('clip-summary').textContent, /Original: 30 s/);
    assert.equal(media.plays, plays + 1);
  };
  assertLocked(); release(response({job_id: child}, 202)); await inFlight; await settle(); assertLocked();
  assert.equal(getTake().active, true);
  setHandler(url => response(url.endsWith('/capsule') ? {...capsule, job_id: child} : url === '/api/h3/readiness' ? {ready: true, limits: {max_clip_seconds: 15}} : {...base, id: child, status: 'done', result_url: `/api/jobs/${child}/result`}));
  await getTake().poll(getTake().epoch);
  assert.equal(el('clip-start').disabled, false); assert.deepEqual(range(), ['2', '5']);
  metadata(3); assert.match(el('clip-summary').textContent, /Original: 30 s/);
  const afterDone = postCount(), savedURL = media.src;
  edit('10', '13'); el('clip-preview').click();
  assert.match(media.src, /^blob:/); assert.notEqual(media.src, savedURL);
  assert.equal(media.currentTime, 10); assert.deepEqual(range(), ['10', '13']);
  metadata(30); media.currentTime = 13.1; media.events.timeupdate();
  assert.equal(media.currentTime, 13); assert.equal(postCount(), afterDone);
  assert.match(el('clip-summary').textContent, /Original: 30 s · Selected: 3 s/);
  select('short.mp4'); metadata(8);
  assert.deepEqual(range(), ['0', '8']); assert.equal(el('submit').disabled, false);
  assert.equal(el('source-clip').hidden, true); assert.equal(el('clip-start').disabled, true); assert.equal(el('clip-end').disabled, true);
  assert.match(el('source-summary-meta').textContent, /Whole clip · 8 s/);
  const whole = new FormData(el('form'));
  assert.equal(whole.has('clip_start_seconds'), false); assert.equal(whole.has('clip_end_seconds'), false);
  let shortPayload;
  setHandler((url, options) => url === '/api/h3/jobs'
    ? (shortPayload = options.body, response({detail: 'Controlled test refusal'}, 422)) : response({ready: true}));
  await submit(); assert.equal(shortPayload.has('clip_start_seconds'), false); assert.equal(shortPayload.has('clip_end_seconds'), false);
  assert.match(el('clip-limit').textContent, /15/); assert.match(el('clip-summary').textContent, /Selected: 8 s/);
  select('bad.mp4'); media.currentSrc = media.src; media.events.error();
  assert.equal(el('submit').disabled, true); assert.match(el('clip-status').textContent, /browser-playable MP4/);
  const last = postCount(); await submit(); assert.equal(postCount(), last);
  assert.equal(el('source-clip').hidden, true);
  console.log('H3 clip studio checks passed: valid long default, no invalid POST/FormData, exact [2,5], stale metadata, preserved edits, locked events and explicit bounded preview.');
}

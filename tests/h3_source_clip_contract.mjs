// CPU-only tests of the real excerpt controller; no server or generation.
import assert from 'node:assert/strict';
import {SourceClip} from '../src/static/source-clip.js';
class Element {
  constructor() { Object.assign(this, {value: '', disabled: false, hidden: false, attrs: {}, events: new Map(), textContent: '', currentTime: 0, plays: 0, pauses: 0}); }
  addEventListener(name, fn) { if (!this.events.has(name)) this.events.set(name, new Set()); this.events.get(name).add(fn); }
  removeEventListener(name, fn) { this.events.get(name)?.delete(fn); }
  emit(name) { for (const fn of [...(this.events.get(name) || [])]) fn(); }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name]; }
  setCustomValidity(value) { this.validity = value; }
  pause() { this.pauses++; }
  play() { this.plays++; return Promise.resolve(); }
  focus() { this.focused = true; }
}
function fixture(options = {}) {
  const nodes = Object.fromEntries(['root', 'start', 'end', 'preview', 'status', 'summary', 'limit', 'media'].map(key => [key, new Element()]));
  let changes = 0, previews = 0;
  const clip = new SourceClip({...nodes, ...options, onChange: () => changes++, onPreview: () => previews++});
  const select = (file = {}, url = 'blob:original', duration) => {
    clip.select(file, url); nodes.media.attrs.src = url; nodes.media.currentSrc = url;
    if (duration !== undefined) { nodes.media.duration = duration; nodes.media.emit('loadedmetadata'); }
    return file;
  };
  const edit = (start, end) => { nodes.start.value = start; nodes.end.value = end; nodes.end.emit('input'); };
  return {...nodes, clip, select, edit, counts: () => ({changes, previews})};
}
const f = fixture();
assert.match(f.limit.textContent, /15/);
assert.equal(f.clip.supported, false);
assert.equal(f.clip.valid, false);
const first = f.select({}, 'blob:first');
assert.equal(f.clip.valid, false, 'pending metadata cannot enable Generate');
assert.match(f.status.textContent, /MP4/);
const oldMetadata = [...f.media.events.get('loadedmetadata')][0];
f.select({}, 'blob:second', 42);
assert.equal(f.clip.valid, false, 'old backend without excerpt capability must not accept long selection');
f.clip.setLimit(15);
assert.equal(f.clip.valid, true);
assert.deepEqual([f.start.value, f.end.value], ['0', '15']);
assert.equal(f.root.hidden, false);
assert.match(f.summary.textContent, /Original: 42 s/);
assert.match(f.summary.textContent, /Selected: 15 s/);
assert.equal(f.media.plays, 0, 'import/metadata must not autoplay');
f.edit('0', '15.01');
assert.equal(f.clip.valid, false); assert.match(f.status.textContent, /15/);
assert.equal(f.end.attrs['aria-invalid'], 'true');
for (const range of [['', '5'], ['NaN', '5'], ['Infinity', '5'], ['-1', '5'], ['5', '5'], ['6', '5'], ['40', '43']]) {
  f.edit(...range); assert.equal(f.clip.validate(), false, `reject ${range}`);
}
f.edit('2', '5');
assert.equal(f.clip.validate(), true);
const data = new FormData(); f.clip.appendTo(data);
assert.deepEqual([...data], [['clip_start_seconds', '2'], ['clip_end_seconds', '5']]);
f.media.duration = 1; oldMetadata();
assert.deepEqual([f.start.value, f.end.value], ['2', '5'], 'late old-file callback cannot reset the range');
f.media.attrs.src = '/api/h3/jobs/saved/source'; f.media.currentSrc = f.media.attrs.src;
f.media.emit('loadedmetadata');
assert.match(f.summary.textContent, /Original: 42 s/, 'saved excerpt metadata is not original-file metadata');
f.media.attrs.src = f.media.currentSrc = 'blob:second';
f.preview.emit('click');
assert.equal(f.media.currentTime, 2); assert.equal(f.media.plays, 1); assert.equal(f.counts().previews, 1);
f.media.currentTime = 5.1; f.media.emit('timeupdate');
assert.equal(f.media.currentTime, 5); assert.ok(f.media.pauses > 0);
f.clip.setLocked(true);
f.edit('3', '7'); f.media.duration = 80; f.media.emit('loadedmetadata'); f.preview.emit('click');
assert.deepEqual([f.start.value, f.end.value], ['2', '5']);
assert.equal(f.media.plays, 1); assert.match(f.summary.textContent, /Original: 42 s/);
assert.equal(f.start.disabled, true); assert.equal(f.end.disabled, true);
f.clip.setLocked(false); assert.equal(f.start.disabled, false);
f.clip.setLimit(10); assert.match(f.limit.textContent, /10/); assert.doesNotMatch(f.limit.textContent, /fallback/);
f.select(first, 'blob:short', 8);
assert.deepEqual([f.start.value, f.end.value], ['0', '8']);
assert.equal(f.clip.valid, true); assert.match(f.summary.textContent, /Selected: 8 s/);
assert.equal(f.root.hidden, true); assert.equal(f.start.disabled, true); assert.equal(f.end.disabled, true);
const whole = new FormData(); whole.set('clip_start_seconds', '99'); f.clip.appendTo(whole);
assert.deepEqual([...whole], [], 'whole short clip omits both multipart fields');
f.select({}, 'blob:exact-limit', 10); assert.equal(f.root.hidden, true);
f.select({}, 'blob:above-limit', 10.001); assert.equal(f.root.hidden, false);
const configurable = fixture({maxSeconds: 4}); configurable.select({}, 'blob:future-engine', 6);
assert.deepEqual([configurable.start.value, configurable.end.value], ['0', '4']);
configurable.clip.setLimit(99); assert.equal(configurable.clip.maxSeconds, 4, 'readiness cannot exceed the configured cap');
f.clip.setLimit(undefined); assert.equal(f.clip.supported, false);
f.select({}, 'blob:unplayable'); f.media.emit('error');
assert.equal(f.clip.valid, false); assert.match(f.status.textContent, /browser-playable MP4/);
f.media.duration = 20; f.media.emit('loadedmetadata');
assert.equal(f.clip.valid, false, 'failed metadata stays failed until a new source selection');
f.select({}, 'blob:aborted'); f.media.emit('abort'); assert.equal(f.clip.valid, false);
f.select({}, 'blob:infinite', Infinity); assert.equal(f.clip.valid, false);
f.select(null, ''); assert.equal(f.clip.valid, false);
console.log('H3 source clip contract checks passed: metadata identity, limits, exact seconds, validation, locks and explicit preview.');

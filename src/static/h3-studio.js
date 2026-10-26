import {byId, validId, request, setStage, loadStageMedia, inspectTakeStage} from './h3-http.js';
import {H3Take} from './h3-take.js';
import {SourceClip} from './source-clip.js';

const form = byId('form');
window.OpenGenjutsuStudio?.mountResultLayout?.();
let pending = false, ready = false, readinessEpoch = 0;
const blobs = new Map();
const files = new Map();
const H3_STAGES = ['source', 'reference', 'result'];
// The chain follows both the form and the restored take, so a reopened take shows the
// references it actually consumed.
const take = new H3Take(() => { paintChain(); update(); }, checkReadiness, stage => setStage(stage));
const clip = new SourceClip({root: byId('source-clip'), start: byId('clip-start'), end: byId('clip-end'),
  preview: byId('clip-preview'), status: byId('clip-status'), summary: byId('clip-summary'),
  limit: byId('clip-limit'), media: byId('source-preview'), onChange: () => { paintSourceSummary(); update(); },
  onPreview: () => { previewInputs(); setStage('source'); }});

// One stage state, exactly like the LTX studio: whichever media exists wins.
function syncStage() {
  for (const kind of H3_STAGES) if (byId(`${kind}-preview`).getAttribute('src')) return setStage(kind);
  return setStage('empty');
}

function update() {
  const locked = pending || take.active;
  byId('native-state').inert = locked;
  clip.setLocked(locked);
  for (const field of ['video', 'reference', 'seed', 'native-capture', 'add-second-reference', 'remove-reference']) byId(field).disabled = locked;
  byId('reference-2').disabled = locked || byId('second-reference').hidden;
  for (const field of ['edit', 'description']) byId(field).disabled = locked || !byId('directions').open;
  const inputs = byId('video').files.length === 1 && byId('reference').files.length === 1;
  // Readiness is advisory here: the server checks the target again and returns the exact reason.
  byId('submit').disabled = locked || !inputs || !clip.valid;
  byId('replay').disabled = locked || !take.capsule;
  byId('form-help').textContent = locked ? 'A take is being submitted or tracked.'
    : byId('video').files.length && !clip.valid ? byId('clip-status').textContent
    : !inputs ? 'Add one source video and one character reference. No prompt needed.'
    : ready ? 'Ready to generate.'
    : 'H3 availability is unverified. You can still submit; the server rechecks it and reports the exact reason.';
}
async function checkReadiness() {
  const epoch = ++readinessEpoch;
  ready = false;
  take.ready = false;
  update();
  const badge = byId('readiness');
  const notes = byId('notices');
  badge.classList.remove('live');
  badge.textContent = 'Checking local studio…';
  notes.hidden = true;
  try {
    const report = await request('/api/h3/readiness' + (byId('native-capture').checked ? '?native_capture=true' : ''), {signal: AbortSignal.timeout(20000)});
    if (epoch !== readinessEpoch) return false;
    ready = report.ready === true && (!byId('native-capture').checked || report.native_capture_supported === true);
    if (byId('native-capture').checked && report.native_capture_supported !== true) {
      report.issues = ['This application has not confirmed native capture support. Retry availability after the backend update, or uncheck native state.'];
    }
    clip.setLimit(report.limits?.max_clip_seconds);
    badge.classList.toggle('live', ready);
    badge.textContent = ready ? (report.inventory_verified === false ? 'Connected · dependencies unchecked' : 'Studio ready') : (report.issues || ['Studio unavailable']).join(' ');
    notes.textContent = (report.warnings || []).join(' ');
    notes.hidden = !notes.textContent;
  } catch (error) {
    if (epoch !== readinessEpoch) return false;
    ready = false;
    clip.setLimit(undefined);
    badge.textContent = 'Studio unavailable';
    notes.hidden = true;
  }
  take.ready = ready;
  update();
  return ready;
}
function notify(message) {
  window.OpenGenjutsuStudio?.showToast?.(byId('toast-region'), message, 'error');
}
function paintPickers() {
  byId('video-name').textContent = byId('video').files[0] ? byId('video').files[0].name : 'Choose a video';
  for (const [field, suffix, fallback] of [['reference', '', 'Add a clear character image'],
                                           ['reference-2', '-2', 'Add the second character']]) {
    const file = byId(field).files[0];
    byId(`reference-name${suffix}`).textContent = file ? file.name : fallback;
    const url = blobs.get(field);
    byId(`reference-thumb${suffix}`).replaceChildren(
      url ? Object.assign(document.createElement('img'), {src: url, alt: ''}) : '＋');
  }
  byId('remove-reference').hidden = !byId('reference').files[0];
  byId('add-second-reference').hidden = !byId('reference').files[0];
}
function setSecondReference(visible) {
  if (pending || take.active) return;
  byId('second-reference').hidden = !visible;
  update();
  const toggle = byId('add-second-reference');
  toggle.setAttribute('aria-expanded', String(visible));
  toggle.lastElementChild.textContent = visible ? 'Remove second character' : 'Add a second character';
  toggle.firstElementChild.textContent = visible ? '−' : '＋';
  if (visible) return;
  byId('reference-2').value = '';
  previewInputs();
}
function previewInputs() {
  if (pending || take.active) return;
  take.reset();
  for (const [kind, field] of [['source', 'video'], ['reference', 'reference'],
                               ['reference-2', 'reference-2']]) {
    const old = blobs.get(kind);
    const file = byId(field).files[0];
    const changed = files.get(kind) !== file;
    const url = file ? (!changed && old ? old : URL.createObjectURL(file)) : '';
    if (kind === 'source') {
      clip.select(file, url);
      if (changed) byId('source-summary-meta').textContent = '';
    }
    loadStageMedia(kind, url);
    if (changed && old) URL.revokeObjectURL(old);
    blobs.set(kind, url);
    files.set(kind, file);
  }
  paintPickers();
  paintChain();
  paintSourceSummary();
  syncStage();
  update();
}
// One reference or two: the chain shows a card per reference and renumbers itself.
function paintChain() {
  const fromForm = byId('reference-2').files.length === 1 && !byId('second-reference').hidden;
  const fromTake = (take.capsule?.recipe?.reference_count || 0) > 1;
  const second = take.capsule ? fromTake : fromForm;
  byId('take-reference-2-card').hidden = !second;
  byId('take-second-arrow').hidden = !second;
  byId('take-result-card').querySelector('span').textContent = second
    ? '04 · H3 result' : '03 · H3 result';
}
// Mirrors LTX: the frame is followed by the selected source's own summary block.
function paintSourceSummary() {
  const file = byId('video').files[0];
  byId('source-summary').hidden = !file;
  byId('source-summary-name').textContent = file ? file.name : '';
  const meta = byId('source-summary-meta');
  if (!file) { meta.textContent = ''; return; }
  if (clip.state !== 'ready') { meta.textContent = clip.error; return; }
  const media = byId('source-preview');
  const dimensions = clip.matchesMedia() ? ` · ${media.videoWidth}×${media.videoHeight}` : '';
  meta.textContent = `${clip.needsExcerpt ? 'Original' : 'Whole clip'} · ${clip.duration} s${dimensions}`;
}
function submission() {
  if (!clip.validate()) { update(); return null; }
  byId('edit').disabled = !byId('directions').open;
  const seed = byId('seed');
  seed.setCustomValidity('');
  if (!/^[0-9]{1,20}$/.test(seed.value) || BigInt(seed.value) > 18446744073709551615n) {
    seed.closest('details').open = true;
    seed.setCustomValidity('Use an integer from 0 to 18446744073709551615.');
  }
  if (!form.reportValidity()) return null;
  const data = new FormData(form);
  clip.appendTo(data);
  if (!byId('directions').open) {
    data.delete('edit_prompt');
    data.delete('character_description');
  }
  return data;
}
async function submit(event) {
  event.preventDefault();
  if (pending || take.active) return;
  const data = submission();
  if (!data) return;
  const epoch = ++take.epoch;
  pending = true;
  update();
  byId('run-overlay').hidden = false;
  try {
    if (data.get('native_capture') === 'true' && !await checkReadiness()) {
      throw new Error('Native state capture is not confirmed. Check availability or uncheck native state.');
    }
    const projectId = await window.OpenGenjutsuProject?.ensure();
    if (projectId) data.set('project_id', projectId);
    const response = await request('/api/h3/jobs', {method: 'POST', body: data});
    if (epoch !== take.epoch) return;
    if (!validId(response.job_id)) throw new Error('Server returned an invalid H3 job identifier. Check the service before retrying.');
    window.OpenGenjutsuProject?.acceptJob(response.job_id, response.project_id, 'minimax-h3');
    take.watch(response.job_id);
    for (const url of blobs.values()) if (url) URL.revokeObjectURL(url);
    blobs.clear(); // Next draft recreates URLs from the original Files, not the saved excerpt.
  } catch (error) {
    if (epoch !== take.epoch) return;
    take.returnAffordance();
    notify(`Submission not confirmed: ${error.message}`);
    byId('run-overlay').hidden = true;
  } finally {
    pending = false;
    update();
  }
}
form.addEventListener('submit', submit);
byId('directions').addEventListener('toggle', update);
byId('native-capture').addEventListener('change', () => { if (!pending && !take.active) checkReadiness(); });
for (const [field, kind] of [['video', 'source'], ['reference', 'reference'],
                             ['reference-2', 'reference']]) {
  byId(field).addEventListener('change', () => {
    if (pending || take.active) return;
    previewInputs(); setStage(kind);
  });
}
byId('add-second-reference').addEventListener('click', () => {
  setSecondReference(byId('second-reference').hidden);
});
// The capsule marks each take stage and selects it in the preview frame.
for (const card of document.querySelectorAll?.('[data-h3-stage]') || []) {
  card.addEventListener('click', () => {
    inspectTakeStage(card.dataset.h3Stage,card.id==='h3-take-reference-2-card');
  });
}
byId('remove-reference').addEventListener('click', () => {
  if (pending || take.active) return;
  byId('reference').value = '';
  if (!byId('second-reference').hidden) setSecondReference(false);
  byId('reference').value = '';
  previewInputs();
});
// Same shared drag/drop implementation as the LTX studio; unsupported drops keep the current file.
window.OpenGenjutsuStudio?.bindFileDropTargets?.(notify);
byId('seed').addEventListener('input', () => byId('seed').setCustomValidity(''));
for (const kind of ['source', 'reference', 'result']) {
  byId(`${kind}-preview`).addEventListener('error', () => {
    if (kind === 'source' && clip.matchesMedia()) return; // The excerpt controller owns local-file failures.
    loadStageMedia(kind, '');
    if (kind === 'result') take.clearResult();
    notify(`${kind} preview unavailable. Retry status.`);
    syncStage();
  });
}
window.addEventListener('pagehide', () => {
  for (const url of blobs.values()) if (url) URL.revokeObjectURL(url);
});
update();
checkReadiness();
take.resume();
if (typeof location !== 'undefined' && new URLSearchParams(location.search).has('character_id')) {
  import('./character-handoff.js').then(({applyCharacterReference}) => applyCharacterReference({
    input: byId('reference'), notify: message => window.OpenGenjutsuStudio?.showToast?.(byId('toast-region'), message),
    isBusy: () => pending || take.active,
  })).catch(() => notify('The character transfer is unavailable. Reload the studio to retry.'));
}
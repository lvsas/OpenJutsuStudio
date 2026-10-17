import {byId, validId, request, showMedia} from './h3-http.js';
import {H3Take} from './h3-take.js';

const form = byId('form');
let pending = false, ready = false, readinessEpoch = 0;
const blobs = new Map();
const take = new H3Take(() => update(), checkReadiness);

function update() {
  const locked = pending || take.active;
  for (const field of ['video', 'reference', 'seed']) byId(field).disabled = locked;
  byId('edit').disabled = locked || !byId('directions').open;
  const inputs = byId('video').files.length === 1 && byId('reference').files.length === 1;
  // Readiness is advisory here: the server checks the target again and returns the exact reason.
  byId('submit').disabled = locked || !inputs;
  byId('replay').disabled = locked || !take.capsule;
  byId('form-help').textContent = locked ? 'A take is being submitted or tracked. Retry status if the connection is interrupted.'
    : !inputs ? 'Add one source video and one character reference. No prompt needed.'
    : ready ? 'Ready to generate an H3 take.'
    : 'H3 availability is unverified. You can still submit; the server rechecks it and reports the exact reason.';
}
async function checkReadiness() {
  const epoch = ++readinessEpoch;
  ready = false;
  take.ready = false;
  update();
  byId('readiness').textContent = 'Checking H3 availability…';
  const notes = byId('readiness-notes');
  notes.replaceChildren();
  try {
    const report = await request('/api/h3/readiness', {signal: AbortSignal.timeout(20000)});
    if (epoch !== readinessEpoch) return false;
    ready = report.ready === true;
    byId('readiness').textContent = ready ? 'H3 ready' : 'H3 not ready';
    for (const message of [...(report.issues || []), ...(report.warnings || [])]) {
      const item = document.createElement('li');
      item.textContent = String(message);
      notes.append(item);
    }
    if (!ready && !notes.childElementCount) byId('readiness').textContent = 'H3 not ready. Check the studio configuration.';
  } catch (error) {
    if (epoch !== readinessEpoch) return false;
    ready = false;
    byId('readiness').textContent = `H3 availability unknown: ${error.message}`;
  }
  take.ready = ready;
  update();
  return ready;
}
function notify(message) {
  const status = byId('status');
  status.textContent = message;
  status.setAttribute('role', 'alert');
}
function paintPickers() {
  for (const [field, fallback] of [['video', 'Choose one continuous shot'], ['reference', 'Add a clear character image']]) {
    const file = byId(field).files[0];
    byId(`${field}-name`).textContent = file ? file.name : fallback;
  }
  const url = blobs.get('reference');
  byId('reference-thumb').replaceChildren(url ? Object.assign(document.createElement('img'), {src: url, alt: ''}) : '＋');
  byId('remove-reference').hidden = !byId('reference').files[0];
}
function previewInputs() {
  take.reset();
  for (const [kind, field] of [['source', 'video'], ['reference', 'reference']]) {
    const old = blobs.get(kind);
    const file = byId(field).files[0];
    const url = file ? URL.createObjectURL(file) : '';
    showMedia(kind, url, `Choose ${kind === 'source' ? 'a source video' : 'one reference image'}.`);
    if (old) URL.revokeObjectURL(old);
    blobs.set(kind, url);
  }
  paintPickers();
  update();
}
function submission() {
  byId('edit').disabled = !byId('directions').open;
  const seed = byId('seed');
  seed.setCustomValidity('');
  if (!/^[0-9]{1,20}$/.test(seed.value) || BigInt(seed.value) > 18446744073709551615n) {
    seed.closest('details').open = true;
    seed.setCustomValidity('Use an integer from 0 to 18446744073709551615.');
  }
  if (!form.reportValidity()) return null;
  const data = new FormData(form);
  if (!byId('directions').open) data.delete('edit_prompt');
  return data;
}
async function submit(event) {
  event.preventDefault();
  if (pending || take.active) return;
  const data = submission();
  if (!data) return;
  pending = true;
  update();
  byId('status').textContent = 'Uploading inputs. Keep this page open until a job identifier is returned.';
  try {
    const response = await request('/api/h3/jobs', {method: 'POST', body: data});
    if (!validId(response.job_id)) throw new Error('Server returned an invalid H3 job identifier. Check the service before retrying.');
    take.watch(response.job_id);
    for (const url of blobs.values()) if (url) URL.revokeObjectURL(url);
    blobs.clear();
  } catch (error) {
    byId('status').textContent = `Submission not confirmed: ${error.message}`;
    byId('status').setAttribute('role', 'alert');
  } finally {
    pending = false;
    update();
  }
}
form.addEventListener('submit', submit);
byId('directions').addEventListener('toggle', update);
for (const field of ['video', 'reference']) byId(field).addEventListener('change', previewInputs);
byId('remove-reference').addEventListener('click', () => {
  byId('reference').value = '';
  previewInputs();
});
// Same shared drag/drop implementation as the LTX studio; unsupported drops keep the current file.
window.OpenGenjutsuStudio?.bindFileDropTargets?.(notify);
byId('seed').addEventListener('input', () => byId('seed').setCustomValidity(''));
byId('retry').addEventListener('click', () => {
  if (pending) return;
  checkReadiness();
  take.resume();
});
for (const kind of ['source', 'reference', 'result']) {
  byId(`${kind}-preview`).addEventListener('error', () => showMedia(kind, '', `${kind} preview unavailable. Check the retained media and retry status.`));
}
window.addEventListener('pagehide', () => {
  for (const url of blobs.values()) if (url) URL.revokeObjectURL(url);
});
update();
checkReadiness();
take.resume();

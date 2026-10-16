const $ = (selector) => document.querySelector(selector);

const form = $('#form');
const button = $('#submit');
const videoInput = $('#video');
const referenceInput = $('#reference');
const editInput = $('#edit');
const sourcePreview = $('#source-preview');
const resultVideo = $('#result');
const stageEmpty = $('#stage-empty');
const runOverlay = $('#run-overlay');
const stageMode = $('#stage-mode');
const sourceSummary = $('#source-summary');
const resultActions = $('#result-actions');
const downloadResult = $('#download-result');
const toastRegion = $('#toast-region');
const statusBox = $('#status');

let activeJob = null;
let pollTimer = null;
let ready = false;
let sourceUrl = null;
let referenceUrl = null;

function showToast(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

function replaceObjectUrl(current, file) {
  if (current) URL.revokeObjectURL(current);
  return URL.createObjectURL(file);
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return '';
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60).toString().padStart(2, '0');
  return `${minutes}:${remainder}`;
}

function setStage(mode) {
  stageEmpty.hidden = mode !== 'empty';
  sourcePreview.hidden = mode !== 'source';
  resultVideo.hidden = mode !== 'result';
  stageMode.textContent = mode === 'result' ? 'Result ready' : mode === 'source' ? 'Source preview' : 'Awaiting media';
}

function updateGenerateEnabled() {
  button.disabled = !ready || Boolean(activeJob) || !videoInput.files[0] || editInput.value.trim().length < 3;
}

function renderSourceMetadata() {
  const file = videoInput.files[0];
  if (!file) return;
  $('#video-file-name').textContent = file.name;
  $('#source-summary-name').textContent = file.name;
  sourcePreview.onloadedmetadata = () => {
    const meta = `${formatDuration(sourcePreview.duration)} · ${sourcePreview.videoWidth}×${sourcePreview.videoHeight}`;
    $('#video-file-meta').textContent = meta;
    $('#source-summary-meta').textContent = meta;
    sourceSummary.hidden = false;
  };
}

function previewSource() {
  const file = videoInput.files[0];
  if (!file) return;
  sourceUrl = replaceObjectUrl(sourceUrl, file);
  sourcePreview.src = sourceUrl;
  renderSourceMetadata();
  resultActions.hidden = true;
  setStage('source');
  updateGenerateEnabled();
}

function previewReference() {
  const file = referenceInput.files[0];
  if (!file) return;
  referenceUrl = replaceObjectUrl(referenceUrl, file);
  const thumbnail = $('#reference-thumb');
  thumbnail.replaceChildren(Object.assign(document.createElement('img'), { src: referenceUrl, alt: '' }));
  $('#reference-file-name').textContent = file.name;
}

function humanStage(job) {
  if (job.status === 'queued') return ['Queued for the local studio', 'Your video is ready to start.'];
  if (job.status === 'done') return ['Your edit is ready', 'Review the result, download it, or copy a caption.'];
  if (job.status === 'error') return ['This edit could not finish', job.error || 'The local pipeline returned an unknown error.'];
  if (job.step === 'detect_scenes') return ['Reading your video', 'Finding clean editing boundaries.'];
  if (job.step?.startsWith('edit_segment')) return ['Creating and propagating the edit', 'Keeping your timing and camera movement.'];
  if (job.step === 'merge_segments') return ['Finishing your video', 'Joining the edited moments.'];
  if (job.step === 'upscale') return ['Finishing in Studio HD', 'Preparing the final image detail.'];
  return ['Preparing your edit', 'Validating media and local models.'];
}

function updateProgress(job) {
  const [title, detail] = humanStage(job);
  $('#run-title').textContent = title;
  $('#run-detail').textContent = detail;
  $('#progress-fill').style.width = `${Math.max(4, Math.min(100, (job.progress || 0) * 100))}%`;
  statusBox.textContent = `${title}. ${detail}`;
}

function showResult(job) {
  resultVideo.src = job.result_url;
  downloadResult.href = `${job.result_url}?download=true`;
  runOverlay.hidden = true;
  resultActions.hidden = false;
  setStage('result');
}

function renderJob(job) {
  updateProgress(job);
  if (job.status === 'done' && job.result_url) {
    showResult(job);
    activeJob = null;
    localStorage.removeItem('opengenjutsu_job');
    updateGenerateEnabled();
    return true;
  }
  if (job.status === 'error') {
    runOverlay.hidden = true;
    activeJob = null;
    localStorage.removeItem('opengenjutsu_job');
    showToast(job.error || 'Generation failed.', 'error');
    setStage(sourcePreview.src ? 'source' : 'empty');
    updateGenerateEnabled();
    return true;
  }
  runOverlay.hidden = false;
  return false;
}

async function poll(id) {
  activeJob = id;
  localStorage.setItem('opengenjutsu_job', id);
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || 'Job not found.');
    if (!renderJob(job)) pollTimer = window.setTimeout(() => poll(id), 2400);
  } catch (error) {
    runOverlay.hidden = true;
    activeJob = null;
    updateGenerateEnabled();
    showToast(`Unable to track the edit: ${error.message}`, 'error');
  }
}

async function checkConnection() {
  const indicator = $('#readiness');
  try {
    const response = await fetch('/api/readiness');
    const report = await response.json();
    ready = response.ok && report.ready;
    indicator.classList.toggle('live', ready);
    indicator.textContent = ready ? 'Local studio ready' : (report.issues || ['Studio unavailable']).join(' ');
  } catch {
    ready = false;
    indicator.textContent = 'Local studio unavailable';
  }
  updateGenerateEnabled();
}

async function copyCaption() {
  const caption = 'Made with OpenGenjutsu — an open-source local video transformation studio built with LTX on ComfyUI.';
  try {
    await navigator.clipboard.writeText(caption);
    showToast('Caption copied. Add your downloaded result before posting.');
  } catch {
    showToast('Clipboard access was unavailable. Copy the caption manually.', 'error');
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!videoInput.files[0] || editInput.value.trim().length < 3) {
    showToast('Choose a source video and describe the transformation first.', 'error');
    return;
  }
  button.disabled = true;
  resultActions.hidden = true;
  runOverlay.hidden = false;
  updateProgress({ status: 'running', progress: .03, step: 'init' });
  try {
    const response = await fetch('/api/jobs', { method: 'POST', body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Unable to start the edit.');
    renderJob(payload.job);
    poll(payload.job_id);
  } catch (error) {
    runOverlay.hidden = true;
    activeJob = null;
    updateGenerateEnabled();
    showToast(error.message, 'error');
  }
});

videoInput.addEventListener('change', previewSource);
referenceInput.addEventListener('change', previewReference);
editInput.addEventListener('input', updateGenerateEnabled);
$('#show-source').addEventListener('click', () => setStage('source'));
$('#show-result').addEventListener('click', () => setStage('result'));
$('#copy-caption').addEventListener('click', copyCaption);
window.addEventListener('beforeunload', () => {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  if (referenceUrl) URL.revokeObjectURL(referenceUrl);
});

checkConnection();
const savedJob = localStorage.getItem('opengenjutsu_job');
if (savedJob) poll(savedJob);

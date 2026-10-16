const $ = (selector) => document.querySelector(selector);
const { formatDuration, replaceObjectUrl, showToast: appendToast } = window.OpenGenjutsuStudio;

const form = $('#form');
const button = $('#submit');
const videoInput = $('#video');
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
const showToast = (message, type) => appendToast(toastRegion, message, type);
const statusBox = $('#status');

let activeJob = null;
let pollTimer = null;
let readinessTimer = null;
let ready = false;
let sourceUrl = null;

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

function humanStage(job) {
  if (job.status === 'queued') return ['Queued for the local studio', 'Your video is ready to start.'];
  if (job.status === 'done') return ['Your edit is ready', 'Review the result, download it, or copy a caption.'];
  if (job.status === 'error') return ['This edit could not finish', job.error || 'The local pipeline returned an unknown error.'];
  if (job.step === 'detect_scenes') return ['Reading your video', 'Finding clean editing boundaries.'];
  if (job.step?.startsWith('prepare_segment')) return ['Preparing this moment', 'Extracting the source frames for this edit.'];
  if (job.step?.startsWith('edit_frame_submitting')) return ['Designing the first frame', 'Submitting your character edit to FLUX.'];
  if (job.step?.startsWith('edit_frame_downloaded')) return ['First frame ready', 'Loading it into the motion workflow.'];
  if (job.step?.startsWith('propagate_submitting')) return ['Creating and propagating the edit', 'LTX is carrying the edit through the clip.'];
  if (job.step?.startsWith('propagate_downloaded')) return ['Motion edit ready', 'Preparing the exact source timing.'];
  if (job.step?.startsWith('trim_segment')) return ['Finishing this moment', 'Restoring the exact clip length.'];
  if (job.step === 'merge_segments') return ['Finishing your video', 'Joining the edited moments.'];
  if (job.step === 'upscale') return ['Finishing in Studio HD', 'Preparing the final image detail.'];
  return ['Preparing your edit', 'Validating media and local models.'];
}

function updateProgress(job) {
  const [title, detail] = humanStage(job);
  $('#run-title').textContent = title;
  $('#run-detail').textContent = detail;
  const progress = Math.max(4, Math.min(100, Math.round((job.progress || 0) * 100)));
  $('#progress-fill').style.width = `${progress}%`;
  $('.progress-track').setAttribute('aria-valuenow', String(progress));
  const segment = job.step?.match(/_(\d+)\/(\d+)$/);
  $('#progress-label').textContent = segment
    ? `${progress}% · moment ${segment[1]} of ${segment[2]}`
    : `${progress}%`;
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
  if (!ready && !readinessTimer) {
    readinessTimer = window.setTimeout(() => {
      readinessTimer = null;
      checkConnection();
    }, 5000);
  }
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
editInput.addEventListener('input', updateGenerateEnabled);
$('#show-source').addEventListener('click', () => setStage('source'));
$('#show-result').addEventListener('click', () => setStage('result'));
$('#copy-caption').addEventListener('click', copyCaption);
window.addEventListener('beforeunload', () => {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (readinessTimer) window.clearTimeout(readinessTimer);
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
});

checkConnection();
const savedJob = localStorage.getItem('opengenjutsu_job');
if (savedJob) poll(savedJob);

const $ = (selector) => document.querySelector(selector);
const { bindFileDropTargets, formatDuration, replaceObjectUrl, showToast: appendToast } = window.OpenGenjutsuStudio;

const videoInput = $('#video');
const sourcePreview = $('#source-preview');
const resultVideo = $('#result');
const anchorStage = $('#anchor-stage');

const compareStage = $('#compare-stage');
const compareSource = $('#compare-source');
const compareResult = $('#compare-result');
const stageEmpty = $('#stage-empty');
const runOverlay = $('#run-overlay');
const stageMode = $('#stage-mode');
const sourceSummary = $('#source-summary');
const resultActions = $('#result-actions');
const downloadResult = $('#download-result');
const buildReelButton = $('#build-reel');
const toastRegion = $('#toast-region');
const showToast = (message, type) => appendToast(toastRegion, message, type);
bindFileDropTargets((message) => showToast(message, 'error'));


let activeJob = null;
let pollTimer = null;
let submission = null;
let sourceUrl = null;
let completedJobId = null;

function setStage(mode) {
  stageEmpty.hidden = mode !== 'empty';
  sourcePreview.hidden = mode !== 'source';
  resultVideo.hidden = mode !== 'result';
  anchorStage.hidden = mode !== 'anchor';
  compareStage.hidden = mode !== 'compare';
  const labels = { empty: 'Awaiting media', source: 'Source preview', anchor: 'FLUX anchor', result: 'Result ready', compare: 'Before / after' };
  stageMode.textContent = labels[mode] || labels.empty;
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
  submission?.refresh();
}

const updateProgress = (job) => window.OpenGenjutsuStudio.renderProgress(job);

function showResult(job) {
  completedJobId = job.id;
  if (job.source_url) sourcePreview.src = job.source_url;
  resultVideo.src = job.result_url;
  downloadResult.href = `${job.result_url}?download=true`;
  buildReelButton.disabled = false;
  runOverlay.hidden = true;
  resultActions.hidden = false;
  window.dispatchEvent(new CustomEvent('opengenjutsu:take-ready', { detail: job }));
  setStage('result');
}


function syncComparison(source, target) {
  if (Math.abs(source.currentTime - target.currentTime) > .15) target.currentTime = source.currentTime;
}

function showComparison() {
  if (!sourcePreview.src || !resultVideo.src) return;
  compareSource.src = sourcePreview.src;
  compareResult.src = resultVideo.src;
  compareSource.muted = true;
  setStage('compare');
}

for (const [source, target] of [[compareSource, compareResult], [compareResult, compareSource]]) {
  source.addEventListener('play', () => { if (target.paused) target.play().catch(() => {}); });
  source.addEventListener('pause', () => { if (!target.paused) target.pause(); });
  source.addEventListener('seeking', () => syncComparison(source, target));
  source.addEventListener('timeupdate', () => syncComparison(source, target));
}

function renderJob(job) {
  updateProgress(job);
  if (job.status === 'done' && job.result_url) {
    showResult(job);
    activeJob = null;
    localStorage.removeItem('opengenjutsu_job');
    submission?.refresh();
    return true;
  }
  if (job.status === 'error') {
    runOverlay.hidden = true;
    activeJob = null;
    localStorage.removeItem('opengenjutsu_job');
    showToast(job.error || 'Generation failed.', 'error');
    setStage(sourcePreview.src ? 'source' : 'empty');
    submission?.refresh();
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
    submission?.refresh();
    showToast(`Unable to track the edit: ${error.message}`, 'error');
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

async function buildComparisonReel() {
  if (!completedJobId) return;
  buildReelButton.disabled = true;
  buildReelButton.textContent = 'Building reel…';
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(completedJobId)}/reveal`, { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Unable to build the comparison reel.');
    const download = document.createElement('a');
    download.href = `${payload.reveal_url}?download=true`;
    download.download = '';
    document.body.append(download);
    download.click();
    download.remove();
    showToast('Your local 9:16 comparison reel is downloading.');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    buildReelButton.disabled = !completedJobId;
    buildReelButton.textContent = 'Build comparison reel';
  }
}

videoInput.addEventListener('change', previewSource);
$('#show-source').addEventListener('click', () => setStage('source'));
$('#show-result').addEventListener('click', () => setStage('result'));
$('#show-compare').addEventListener('click', showComparison);
$('#build-reel').addEventListener('click', buildComparisonReel);
$('#copy-caption').addEventListener('click', copyCaption);
window.addEventListener('opengenjutsu:select-stage', ({ detail }) => {
  if (detail?.stage === 'anchor') setStage('anchor');
  if (detail?.stage === 'source') setStage('source');
  if (detail?.stage === 'result') setStage('result');
});
window.addEventListener('beforeunload', () => {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
});

submission = window.OpenGenjutsuStudio.bindSubmission({
  isBusy: () => Boolean(activeJob),
  onBegin: () => {
    resultActions.hidden = true;
    runOverlay.hidden = false;
    updateProgress({ status: 'running', progress: .03, step: 'init' });
  },
  onQueued: (payload) => { renderJob(payload.job); poll(payload.job_id); },
  onFailure: () => { runOverlay.hidden = true; activeJob = null; },
  toast: showToast,
});
const savedJob = localStorage.getItem('opengenjutsu_job');
if (savedJob) poll(savedJob);

const $ = (selector) => document.querySelector(selector);
window.OpenGenjutsuStudio?.mountResultLayout?.();
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
let epoch = 0, submissionEpoch = 0;
const validId = id => typeof id === 'string' && /^[a-f0-9]{32}$/.test(id);
const historyKey = kind => {
  const base = `opengenjutsu.ltx.${kind}-job`;
  return window.OpenGenjutsuProject?.storageKey(base) || base;
};
function jobHistory(kind, value) {
  try {
    if (value === undefined) return localStorage.getItem(historyKey(kind));
    if (value) localStorage.setItem(historyKey(kind), value);
    else localStorage.removeItem(historyKey(kind));
  } catch { /* Generation still works without browser storage. */ }
}
let lastCompletedId = jobHistory('completed');
if (!validId(lastCompletedId)) lastCompletedId = null;
function returnAffordance() {
  $('#return-last').hidden = !lastCompletedId || !resultActions.hidden;
  $('#return-last').disabled = Boolean(activeJob);
}
function detachTracking() {
  epoch += 1;
  window.clearTimeout(pollTimer);
  activeJob = null;
  jobHistory('current', null);
  runOverlay.hidden = true;
}
function validJob(job, id) {
  if (!validId(id) || job.id !== id || job.engine !== 'ltx25-ripple') throw new Error('This is not a valid saved LTX swap.');
  if (!['queued', 'running', 'done', 'error', 'failed', 'cancelled'].includes(job.status)) throw new Error('Unknown swap state.');
  if (job.status === 'done' && job.result_url !== `/api/jobs/${id}/result`) throw new Error('The completed result is unavailable.');
}
async function readJob(id) {
  if (!validId(id)) throw new Error('Invalid swap identifier.');
  const response = await fetch(`/api/jobs/${id}`);
  const job = await response.json();
  if (!response.ok) throw new Error(job.detail || 'Swap not found.');
  validJob(job, id);
  return job;
}
async function restoreCompleted() {
  const id = lastCompletedId;
  if (!validId(id) || activeJob) return;
  const current = ++epoch;
  try {
    const job = await readJob(id);
    if (job.status !== 'done') throw new Error('The saved swap has no completed result.');
    const media = await fetch(job.result_url, { headers: { Range: 'bytes=0-0' } });
    await media.body?.cancel();
    if (!media.ok) throw new Error('The saved result is no longer available.');
    if (current === epoch) showResult(job);
  } catch (error) {
    if (current === epoch) { showToast(error.message, 'error'); returnAffordance(); }
  }
}

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
  if (activeJob || videoInput.disabled) return;
  const file = videoInput.files[0];
  if (!file) return;
  detachTracking();
  sourceUrl = replaceObjectUrl(sourceUrl, file);
  sourcePreview.src = sourceUrl;
  renderSourceMetadata();
  resultActions.hidden = true;
  returnAffordance();
  setStage('source');
  submission?.refresh();
}

const updateProgress = (job) => window.OpenGenjutsuStudio.renderProgress(job);

function showResult(job) {
  completedJobId = lastCompletedId = job.id;
  if (!window.OpenGenjutsuProject || window.OpenGenjutsuProject.containsJob(job.id)) jobHistory('completed', job.id);
  if (job.source_url) sourcePreview.src = job.source_url;
  resultVideo.src = job.result_url;
  downloadResult.href = `${job.result_url}?download=true`;
  const timelineLink = $('#open-timeline');
  if (timelineLink) timelineLink.href = `/timeline?job_id=${job.id}`;
  buildReelButton.disabled = false;
  runOverlay.hidden = true;
  resultActions.hidden = false;
  returnAffordance();
  $('#completion-more').open = false;
  $('#take-inspection').open = false;
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
    jobHistory('current', null);
    submission?.refresh();
    return true;
  }
  if (['error', 'failed', 'cancelled'].includes(job.status)) {
    runOverlay.hidden = true;
    activeJob = null;
    jobHistory('current', null);
    showToast(job.error || 'Generation failed.', 'error');
    resultActions.hidden = true;
    returnAffordance();
    setStage(sourcePreview.src ? 'source' : 'empty');
    submission?.refresh();
    return true;
  }
  runOverlay.hidden = false;
  return false;
}

async function poll(id, current = epoch) {
  if (current !== epoch) return;
  activeJob = id;
  submission?.refresh();
  jobHistory('current', id);
  returnAffordance();
  try {
    const job = await readJob(id);
    if (current !== epoch) return;
    if (job.status === 'done') {
      const media = await fetch(job.result_url, { headers: { Range: 'bytes=0-0' } });
      if (current !== epoch) return;
      await media.body?.cancel();
      if (current !== epoch) return;
      if (!media.ok) throw new Error('The completed result is unavailable.');
    }
    if (!renderJob(job)) pollTimer = window.setTimeout(() => poll(id, current), 2400);
  } catch (error) {
    if (current !== epoch) return;
    runOverlay.hidden = true;
    activeJob = null;
    jobHistory('current', null);
    returnAffordance();
    submission?.refresh();
    showToast(`Unable to track the edit: ${error.message}`, 'error');
  }
}

async function copyCaption() {
  const caption = 'Same moment. New character. Made with Open Jutsu Studio. #OpenJutsuStudio #CharacterSwap';
  try {
    await navigator.clipboard.writeText(caption);
    showToast('Caption copied. Add your downloaded result before posting.');
  } catch {
    showToast('Clipboard access was unavailable. Copy the caption manually.', 'error');
  }
}

function buildComparisonReel() {
  if (!completedJobId || resultActions.hidden) return;
  if (!window.OpenGenjutsuShare?.open) return showToast('Share preview is unavailable. Reload the studio to retry.', 'error');
  window.OpenGenjutsuShare.open({ jobId: completedJobId, resultUrl: resultVideo.src, returnFocus: buildReelButton });
}

videoInput.addEventListener('change', previewSource);
$('#return-last').addEventListener('click', restoreCompleted);
$('#form').addEventListener('change', () => {
  if (activeJob || videoInput.disabled) return;
  detachTracking();
  resultActions.hidden = true;
  returnAffordance();
});
resultVideo.addEventListener('error', () => {
  resultActions.hidden = true;
  returnAffordance();
  setStage(sourcePreview.src ? 'source' : 'empty');
  showToast('Result preview unavailable. Return to last swap to retry.', 'error');
});
window.addEventListener('opengenjutsu:resume-job', ({ detail }) => {
  if (!validId(detail?.id)) return;
  detachTracking();
  resultActions.hidden = true;
  poll(detail.id);
});
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
    detachTracking();
    submissionEpoch = epoch;
    resultActions.hidden = true;
    returnAffordance();
    runOverlay.hidden = false;
    updateProgress({ status: 'running', progress: .03, step: 'init' });
  },
  onQueued: (payload) => {
    if (submissionEpoch !== epoch) return;
    validJob(payload.job, payload.job_id);
    window.OpenGenjutsuProject?.acceptJob(payload.job_id, payload.job.project_id, payload.job.engine);
    poll(payload.job_id);
  },
  onFailure: () => {
    if (submissionEpoch !== epoch) return;
    runOverlay.hidden = true; activeJob = null; returnAffordance();
  },
  toast: (message, type) => { if (submissionEpoch === epoch) showToast(message, type); },
});
async function resumeProject() {
  const scope = window.OpenGenjutsuProject;
  const openingEpoch = epoch;
  if (scope) await scope.ready;
  if (openingEpoch !== epoch) return;
  const explicit = typeof location !== 'undefined' ? new URLSearchParams(location.search).get('job_id') : null;
  const recovered = scope?.recovery('ltx25-ripple');
  lastCompletedId = jobHistory('completed');
  if (!validId(lastCompletedId) || (scope && !scope.containsJob(lastCompletedId))) lastCompletedId = null;
  let savedJob = jobHistory('current');
  if (scope && !scope.containsJob(savedJob)) savedJob = null;
  if (validId(explicit)) { poll(explicit); return; }
  if (validId(savedJob)) poll(savedJob);
  else if (recovered && recovered.status !== 'done') poll(recovered.job_id);
  else {
    jobHistory('current', null);
    lastCompletedId ||= recovered?.job_id || null;
    restoreCompleted();
  }
  returnAffordance();
}
resumeProject().catch(error => showToast(error.message, 'error'));
returnAffordance();
if (typeof location !== 'undefined' && new URLSearchParams(location.search).has('character_id')) {
  import('./character-handoff.js').then(({applyCharacterReference}) => applyCharacterReference({
    input: $('#reference'), notify: showToast,
    isBusy: () => Boolean(activeJob) || !runOverlay.hidden,
  })).catch(() => showToast('The character transfer is unavailable. Reload the studio to retry.', 'error'));
}

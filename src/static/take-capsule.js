(() => {
  const $ = (selector) => document.querySelector(selector);
  const panel = $('#result-actions');
  const downloadLink = $('#download-result');
  const downloadButton = $('#download-capsule');
  const replayButton = $('#replay-capsule');
  const status = $('#capsule-status');
  const inspector = $('#capsule-details');
  const manifestView = $('#capsule-manifest');
  if (!panel || !downloadLink || !downloadButton || !replayButton || !status) return;

  let activeJobId = null;
  let capsule = null;
  let epoch = 0;
  $('#form')?.addEventListener('change', () => { epoch += 1; activeJobId = null; capsule = null; });
  const sourcePreview = $('#source-preview');
  const sourceSummary = $('#source-summary');

  function jobIdFromResultLink() {
    try {
      const url = new URL(downloadLink.href, window.location.origin);
      return url.pathname.match(/^\/api\/jobs\/([A-Za-z0-9_-]+)\/result$/)?.[1] || null;
    } catch {
      return null;
    }
  }

  function replayUnavailableReason(payload) {
    const reasons = [];
    if (!payload.recipe) reasons.push('no recorded recipe');
    if (!payload.shot_boundaries?.length) reasons.push('no recorded shot boundaries');
    if (payload.replay.missing_local_assets?.length) reasons.push(`missing ${payload.replay.missing_local_assets.join(', ')}`);
    return reasons.join('; ') || 'local assets or models are not ready';
  }

  function toast(message, type) {
    const studio = window.OpenGenjutsuStudio;
    if (studio?.showToast) studio.showToast($('#toast-region'), message, type);
  }

  async function loadCapsule() {
    const jobId = jobIdFromResultLink();
    if (!jobId || jobId === activeJobId) return;
    const current = ++epoch;
    activeJobId = jobId;
    capsule = null;
    downloadButton.disabled = true;
    replayButton.disabled = true;
    if (inspector) inspector.hidden = true;
    if (manifestView) manifestView.textContent = '';
    status.textContent = 'Checking local assets and recording their fingerprints…';
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/capsule`);
      const payload = await response.json();
      if (current !== epoch || panel.hidden || jobId !== jobIdFromResultLink()) return;
      if (!response.ok) throw new Error(payload.detail || 'Take Capsule is unavailable.');
      if (payload.job_id !== jobId || payload.engine !== 'ltx25-ripple') throw new Error('Take Passport identity mismatch.');
      capsule = payload;
      downloadButton.disabled = false;
      replayButton.disabled = !payload.replay.available_on_this_machine;
      const shortId = payload.capsule_id.slice(7, 19);
      const parent = payload.parent_job_id ? ` · re-run of ${payload.parent_job_id.slice(0, 8)}` : '';
      const replayNote = payload.replay.available_on_this_machine
        ? 'Ready to re-run on this device.' : `Replay unavailable: ${replayUnavailableReason(payload)}.`;
      const anchors = payload.assets.anchors || [];
      const anchorNote = anchors.length
        ? `${anchors.length} FLUX anchor${anchors.length > 1 ? 's' : ''} fingerprinted with this take.`
        : 'This legacy take has no recorded FLUX anchor.';
      status.textContent = `Take ${shortId}${parent}. ${anchorNote} ${replayNote}`;
      if (inspector && manifestView) {
        manifestView.textContent = JSON.stringify({
          recipe: payload.recipe, shot_boundaries: payload.shot_boundaries,
          assets: payload.assets, replay: payload.replay,
        }, null, 2);
        inspector.hidden = false;
      }
      if (sourcePreview && !sourcePreview.getAttribute('src')) {
        sourcePreview.src = `/api/jobs/${encodeURIComponent(jobId)}/source`;
        sourcePreview.load();
        if (sourceSummary) {
          $('#source-summary-name').textContent = 'Source video from this take';
          $('#source-summary-meta').textContent = 'Loaded from local job history';
          sourceSummary.hidden = false;
        }
      }
    } catch (error) {
      if (current !== epoch) return;
      status.textContent = error.message;
      downloadButton.disabled = true;
      replayButton.disabled = true;
      activeJobId = null;
    }
  }

  downloadButton.addEventListener('click', async () => {
    if (!capsule) await loadCapsule();
    if (!capsule) return;
    const blob = new Blob([JSON.stringify(capsule, null, 2)], { type: 'application/json' });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = `opengenjutsu-take-${activeJobId}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    toast('Take Capsule downloaded. Media files remain local.');
  });

  replayButton.addEventListener('click', async () => {
    if (!activeJobId || replayButton.disabled) return;
    const current = ++epoch;
    replayButton.disabled = true;
    replayButton.textContent = 'Starting replay…';
    status.textContent = 'Starting a linked local re-run with the recorded recipe and shot boundaries…';
    try {
      const projectId = await window.OpenGenjutsuProject?.ensure();
      const options = projectId ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:projectId})} : {method:'POST'};
      const response = await fetch(`/api/jobs/${encodeURIComponent(activeJobId)}/replay`, options);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not start this take again.');
      if (current !== epoch) return;
      window.OpenGenjutsuProject?.acceptJob(payload.job_id, payload.project_id, 'ltx25-ripple');
      window.dispatchEvent(new CustomEvent('opengenjutsu:resume-job', { detail: { id: payload.job_id } }));
    } catch (error) {
      if (current !== epoch) return;
      status.textContent = error.message;
      replayButton.disabled = false;
      replayButton.textContent = 'Re-run this take';
      toast(error.message, 'error');
    }
  });

  const observer = new MutationObserver(() => {
    if (!panel.hidden) loadCapsule();
    else { epoch += 1; activeJobId = null; capsule = null; }
  });
  observer.observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  if (!panel.hidden) loadCapsule();
  window.addEventListener('beforeunload', () => observer.disconnect(), { once: true });
})();

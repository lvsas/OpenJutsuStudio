(() => {
  // One progress renderer for both studios. The caller passes its element-id
  // prefix so each studio keeps its own id convention without a second module.
  const ENGINES = {
    'ltx25-ripple': {
      queued: ['Queued for the local studio', 'Your video is ready to start.'],
      done: ['Your edit is ready', 'Review the result, download it, or copy a caption.'],
      failed: 'This edit could not finish',
      unknown: ['Preparing your edit', 'Validating media and local models.'],
      steps: {
        detect_scenes: ['Reading your video', 'Finding clean editing boundaries.'],
        prepare_segment: ['Preparing this moment', 'Extracting the source frames for this edit.'],
        edit_frame_submitting: ['Designing the first frame', 'Submitting your character edit to FLUX.'],
        edit_frame_downloaded: ['First frame ready', 'Loading it into the motion workflow.'],
        propagate_submitting: ['Creating and propagating the edit', 'LTX is carrying the edit through the clip.'],
        propagate_downloaded: ['Motion edit ready', 'Preparing the exact source timing.'],
        trim_segment: ['Finishing this moment', 'Restoring the exact clip length.'],
        merge_segments: ['Finishing your video', 'Joining the edited moments.'],
        upscale: ['Finishing in Studio HD', 'Preparing the final image detail.'],
      },
    },
    'minimax-h3': {
      queued: ['Queued for the H3 studio', 'Your take is ready to start.'],
      done: ['Your edit is ready', 'Review the result, download it, or copy a caption.'],
      failed: 'This take could not finish',
      unknown: ['Preparing your take', 'Validating media and the H3 service.'],
      steps: {
        h3_prepare: ['Preparing your source and reference', 'Normalizing the clip and freezing the recipe.'],
        h3_submitting: ['Creating the H3 take', 'MiniMax H3 is carrying the character swap through the clip.'],
        h3_assemble: ['Finishing your take', 'Trimming to the exact source length and keeping the audio.'],
      },
    },
  };

  function humanStage(job, copy) {
    if (job.status === 'queued') return copy.queued;
    if (job.status === 'done') return copy.done;
    if (job.status === 'error') return [copy.failed, job.error || 'The local pipeline returned an unknown error.'];
    const step = (job.step || '').replace(/_\d+\/\d+$/, '');
    return copy.steps[step] || copy.unknown;
  }

  window.OpenGenjutsuStudio.renderProgress = (job, prefix = '') => {
    const $ = (id) => document.getElementById(prefix + id);
    // Never let a missing element take down the caller: LTX only reveals the run
    // overlay after this returns, so one absent node would hide the whole overlay.
    const text = (id, value) => { const node = $(id); if (node) node.textContent = value; };
    const copy = ENGINES[job.engine] || ENGINES['ltx25-ripple'];
    const [title, detail] = humanStage(job, copy);
    text('run-title', title);
    text('run-detail', detail);
    const progress = Math.max(4, Math.min(100, Math.round((job.progress || 0) * 100)));
    const fill = $('progress-fill');
    if (fill) fill.style.width = `${progress}%`;
    const track = $('progress-track');
    if (track) track.setAttribute('aria-valuenow', String(progress));
    const segment = job.step?.match(/_(\d+)\/(\d+)$/);
    text('progress-label', segment
      ? `${progress}% · moment ${segment[1]} of ${segment[2]}` : `${progress}%`);
    text('status', `${title}. ${detail}`);
  };
})();

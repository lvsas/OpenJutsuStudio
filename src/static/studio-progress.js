(() => {
  function humanStage(job) {
    if (job.status === 'queued') return ['Queued for the local studio', 'Your video is ready to start.'];
    if (job.status === 'done') return ['Your edit is ready', 'Review the result, download it, or copy a caption.'];
    if (job.status === 'error') return ['This edit could not finish', job.error || 'The local pipeline returned an unknown error.'];
    const stages = {
      detect_scenes: ['Reading your video', 'Finding clean editing boundaries.'],
      prepare_segment: ['Preparing this moment', 'Extracting the source frames for this edit.'],
      edit_frame_submitting: ['Designing the first frame', 'Submitting your character edit to FLUX.'],
      edit_frame_downloaded: ['First frame ready', 'Loading it into the motion workflow.'],
      propagate_submitting: ['Creating and propagating the edit', 'LTX is carrying the edit through the clip.'],
      propagate_downloaded: ['Motion edit ready', 'Preparing the exact source timing.'],
      trim_segment: ['Finishing this moment', 'Restoring the exact clip length.'],
      merge_segments: ['Finishing your video', 'Joining the edited moments.'],
      upscale: ['Finishing in Studio HD', 'Preparing the final image detail.'],
    };
    const step = (job.step || '').replace(/_\d+\/\d+$/, '');
    return stages[step] || ['Preparing your edit', 'Validating media and local models.'];
  }

  window.OpenGenjutsuStudio.renderProgress = (job) => {
    const $ = (selector) => document.querySelector(selector);
    const [title, detail] = humanStage(job);
    $('#run-title').textContent = title;
    $('#run-detail').textContent = detail;
    const progress = Math.max(4, Math.min(100, Math.round((job.progress || 0) * 100)));
    $('#progress-fill').style.width = `${progress}%`;
    $('.progress-track').setAttribute('aria-valuenow', String(progress));
    const segment = job.step?.match(/_(\d+)\/(\d+)$/);
    $('#progress-label').textContent = segment
      ? `${progress}% · moment ${segment[1]} of ${segment[2]}` : `${progress}%`;
    $('#status').textContent = `${title}. ${detail}`;
  };
})();

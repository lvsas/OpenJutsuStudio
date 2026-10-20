(() => {
  const $ = (selector) => document.querySelector(selector);
  const story = $('#take-story');
  const proof = $('#take-story-proof');
  const copy = $('#take-story-copy');
  const source = $('#take-source-preview');
  const result = $('#take-result-preview');
  const anchor = $('#take-anchor-preview');
  const anchorCard = $('#take-anchor-card');
  const anchorButton = $('#show-anchor');
  const pickerWrap = $('#anchor-select-wrap');
  const picker = $('#anchor-select');
  if (!story || !proof || !copy || !source || !result || !anchor || !anchorCard || !anchorButton || !pickerWrap || !picker) return;

  let anchors = [];

  function choose(index) {
    const selected = anchors[index];
    if (!selected) return;
    anchor.src = selected.url;
    $('#anchor-preview').src = selected.url;
    $('#anchor-caption').textContent = `Anchor for source frames ${selected.start}–${selected.end}.`;
    picker.value = String(index);
    window.dispatchEvent(new CustomEvent('opengenjutsu:select-stage', {
      detail: { stage: 'anchor', anchor: selected },
    }));
  }

  function render(job) {
    anchors = Array.isArray(job.anchor_frames) ? job.anchor_frames : [];
    const references = job.meta?.references || (job.meta?.reference_image ? [{}] : []);
    $('#take-reference-note').textContent = references.length
      ? `${references.length} character reference${references.length > 1 ? 's' : ''} recorded with this take. Original reference files remain local.`
      : 'No character reference recorded with this take.';
    story.hidden = false;
    source.src = job.source_url || '';
    result.src = job.result_url || '';
    anchorCard.disabled = anchors.length === 0;
    anchorButton.disabled = anchors.length === 0;
    picker.replaceChildren();
    anchors.forEach((item, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = anchors.length === 1
        ? 'FLUX anchor frame'
        : `Moment ${index + 1} · frames ${item.start}–${item.end}`;
      picker.append(option);
    });
    pickerWrap.hidden = anchors.length < 2;
    if (anchors.length) {
      anchor.src = anchors[0].url;
      proof.textContent = `${anchors.length} FLUX anchor${anchors.length > 1 ? 's' : ''} recorded`;
      copy.textContent = 'Source → FLUX identity anchor → motion result. Re-run keeps this recorded recipe and its shot boundaries.';
    } else {
      anchor.removeAttribute('src');
      proof.textContent = 'Legacy take';
      copy.textContent = 'This completed take predates visual anchor recording. New takes record the FLUX identity anchor before motion propagation.';
    }
  }

  document.querySelectorAll('[data-take-stage]').forEach((button) => {
    button.addEventListener('click', () => {
      const stage = button.dataset.takeStage;
      if (stage === 'anchor') choose(Number(picker.value || 0));
      else window.dispatchEvent(new CustomEvent('opengenjutsu:select-stage', { detail: { stage } }));
    });
  });
  picker.addEventListener('change', () => choose(Number(picker.value)));
  window.addEventListener('opengenjutsu:take-ready', ({ detail }) => render(detail));
})();
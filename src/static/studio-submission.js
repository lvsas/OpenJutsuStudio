(() => {
  const studio = window.OpenGenjutsuStudio;

  studio.bindSubmission = ({ isBusy, onBegin, onQueued, onFailure, toast }) => {
    const form = document.querySelector('#form');
    const button = document.querySelector('#submit');
    const video = document.querySelector('#video');
    const edit = document.querySelector('#edit');
    const directions = document.querySelector('#optional-directions');
    const help = document.querySelector('#generate-help');
    const indicator = document.querySelector('#readiness');
    const notices = document.createElement('p');
    notices.className = 'field-help';
    notices.setAttribute('role', 'status');
    notices.hidden = true;
    help.after(notices);
    let ready = false;
    let submitting = false;
    let timer = null;
    let wasLocked = false;
    const disabledBefore = new Map();
    const hasClip = Boolean(document.querySelector("#source-clip"));

    function selectedReferences() {
      const primary = document.querySelector('#reference');
      const secondary = document.querySelector('#reference-2');
      return [primary, secondary].filter((input) => !input.disabled && input.files[0]
        && (input === primary || !document.querySelector('#second-reference').hidden));
    }

    function refresh() {
      const locked = submitting || isBusy();
      if (locked && !wasLocked) {
        for (const field of form.querySelectorAll?.('input, button, select, textarea') || []) {
          disabledBefore.set(field, field.disabled); field.disabled = true;
        }
      } else if (!locked && wasLocked) {
        for (const [field, disabled] of disabledBefore) field.disabled = disabled;
        disabledBefore.clear();
      }
      wasLocked = locked;
      const clip = window.OpenGenjutsuClip;
      clip?.setLocked(locked);
      edit.disabled = locked || !directions.open;
      const hasIntent = selectedReferences().length > 0 || (!edit.disabled && Boolean(edit.value.trim()));
      button.disabled = !ready || submitting || isBusy() || !video.files[0] || !hasIntent || (hasClip && (!clip || !clip.valid));
      if (submitting || isBusy()) help.textContent = 'Your swap is in progress.';
      else if (!video.files[0]) help.textContent = 'Add your source video to start.';
      else if (hasClip && (!clip || !clip.valid)) help.textContent = clip?.error || 'Loading video controls…';
      else if (!hasIntent) help.textContent = 'Add a character reference, or open Add directions for a text-only swap.';
      else if (!ready) help.textContent = 'Waiting for the local studio to be ready.';
      else help.textContent = selectedReferences().length ? 'Ready to swap. Directions are optional.' : 'Ready to apply your directions.';
    }

    function payload() {
      refresh();
      const data = new FormData(form);
      window.OpenGenjutsuClip?.appendTo(data);
      data.delete('reference_images');
      data.delete('reference_targets');
      selectedReferences().forEach((input) => {
        data.append('reference_images', input.files[0]);
        const target = document.querySelector(input.id === 'reference' ? '#reference-target-1' : '#reference-target-2');
        data.append('reference_targets', target.disabled ? '' : target.value);
      });
      return data;
    }

    async function checkConnection() {
      try {
        const response = await fetch('/api/readiness');
        const report = await response.json();
        ready = response.ok && report.ready;
        studio.clipLimit = report.limits?.max_clip_seconds;
        window.OpenGenjutsuClip?.setLimit(studio.clipLimit);
        indicator.classList.toggle('live', ready);
        indicator.textContent = ready ? (report.inventory_verified === false ? 'Connected · dependencies unchecked' : 'Studio ready') : (report.issues || ['Studio unavailable']).join(' ');
        notices.textContent = (report.warnings || []).join(' ');
        notices.hidden = !notices.textContent;
      } catch {
        ready = false;
        indicator.textContent = 'Studio unavailable';
        notices.textContent = '';
        notices.hidden = true;
      }
      refresh();
      if (!ready && !timer) {
        timer = window.setTimeout(() => { timer = null; checkConnection(); }, 5000);
      }
    }

    async function submit(event) {
      event.preventDefault();
      refresh();
      if (button.disabled) return;
      const data = payload();
      submitting = true;
      refresh();
      onBegin();
      try {
        const projectId = await window.OpenGenjutsuProject?.ensure();
        if (projectId) data.set('project_id', projectId);
        const response = await fetch('/api/jobs', { method: 'POST', body: data });
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Unable to start the swap.');
        onQueued(result);
      } catch (error) {
        onFailure();
        toast(error.message, 'error');
      } finally {
        submitting = false;
        refresh();
      }
    }

    form.addEventListener('submit', submit);
    form.addEventListener('change', refresh);
    edit.addEventListener('input', refresh);
    directions.addEventListener('toggle', refresh);
    window.addEventListener('pageshow', () => {
      directions.open = false;
      edit.value = '';
      refresh();
    });
    window.addEventListener('opengenjutsu:references-changed', refresh);
    window.addEventListener('opengenjutsu:clip-change', refresh);
    window.addEventListener('beforeunload', () => { if (timer) window.clearTimeout(timer); });
    checkConnection();
    return { refresh };
  };
})();
/* Pick a saved character as a swap reference, without leaving the studio.
   The server verifies the character again; this script only chooses ids. */
(() => {
  'use strict';

  function pickerMarkup() {
    const wrap = document.createElement('div');
    wrap.className = 'gallery-picker';
    wrap.innerHTML = `
      <button type="button" class="btn gallery-open">Choose a saved character</button>
      <p class="gallery-summary" role="status" aria-live="polite"></p>
      <dialog class="gallery-dialog">
        <div class="gallery-head">
          <strong>Your characters</strong>
          <button type="button" class="btn gallery-close" aria-label="Close">✕</button>
        </div>
        <div class="gallery-grid"></div>
        <div class="gallery-actions">
          <button type="button" class="btn gallery-confirm">Use these</button>
        </div>
      </dialog>`;
    return wrap;
  }

  function mount(form) {
    const fileInput = form.querySelector('input[type="file"][name="reference_images"]');
    if (!fileInput || form.dataset.galleryPicker === 'on') return;
    form.dataset.galleryPicker = 'on';

    const wrap = pickerMarkup();
    fileInput.insertAdjacentElement('afterend', wrap);
    const open = wrap.querySelector('.gallery-open');
    const dialog = wrap.querySelector('.gallery-dialog');
    const grid = wrap.querySelector('.gallery-grid');
    const summary = wrap.querySelector('.gallery-summary');
    const limit = Number(fileInput.closest('form')?.dataset.maxReferences || 0) || 3;
    const chosen = new Map();

    function sync() {
      form.querySelectorAll('input[type="hidden"][name="reference_job_ids"]').forEach(node => node.remove());
      for (const id of chosen.keys()) {
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = 'reference_job_ids';
        hidden.value = id;
        form.appendChild(hidden);
      }
      const count = chosen.size;
      summary.textContent = count
        ? count + ' saved character' + (count > 1 ? 's' : '') + ' selected'
        : '';
    }

    function render(characters) {
      grid.textContent = '';
      if (!characters.length) {
        const empty = document.createElement('p');
        empty.className = 'gallery-empty';
        empty.innerHTML = 'No saved characters yet. Create one in <a href="/characters">Characters</a>, then save it.';
        grid.appendChild(empty);
        return;
      }
      for (const character of characters) {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'gallery-card';
        card.dataset.jobId = character.job_id;
        card.setAttribute('aria-pressed', 'false');
        const image = document.createElement('img');
        image.src = character.image_url;
        image.alt = character.name || 'Saved character';
        image.loading = 'lazy';
        const label = document.createElement('span');
        label.textContent = character.name || 'Untitled character';
        card.append(image, label);
        card.addEventListener('click', () => {
          const id = character.job_id;
          if (chosen.has(id)) chosen.delete(id);
          else if (chosen.size >= limit) { summary.textContent = 'Up to ' + limit + ' references.'; return; }
          else chosen.set(id, true);
          card.setAttribute('aria-pressed', chosen.has(id) ? 'true' : 'false');
          card.classList.toggle('is-chosen', chosen.has(id));
          sync();
        });
        grid.appendChild(card);
      }
    }

    open.addEventListener('click', async () => {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
      grid.textContent = 'Loading…';
      try {
        const response = await fetch('/api/characters/library', {headers: {Accept: 'application/json'}});
        const data = response.ok ? await response.json() : {characters: []};
        render(Array.isArray(data.characters) ? data.characters : []);
        for (const card of grid.querySelectorAll('.gallery-card')) {
          const on = chosen.has(card.dataset.jobId);
          card.setAttribute('aria-pressed', on ? 'true' : 'false');
          card.classList.toggle('is-chosen', on);
        }
      } catch (error) {
        grid.textContent = 'The character library could not be read.';
      }
    });

    wrap.querySelector('.gallery-close').addEventListener('click', () => dialog.close());
    wrap.querySelector('.gallery-confirm').addEventListener('click', () => dialog.close());
  }

  function boot() {
    document.querySelectorAll('form').forEach(mount);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  else boot();
})();

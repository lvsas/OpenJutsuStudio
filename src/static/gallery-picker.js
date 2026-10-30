/* Fill an existing reference slot from the saved characters, instead of bolting a
   second, unrelated picker next to the form. Each slot keeps its own source, and the
   whole form is described by one ordered list: reference_sources. */
(() => {
  'use strict';

  function slotButton() {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn gallery-slot-open';
    button.textContent = 'From gallery';
    return button;
  }

  function mountSlot(form, input, index, state) {
    if (input.dataset.gallerySlot === 'on') return index + 1;
    input.dataset.gallerySlot = 'on';
    const button = slotButton();
    const badge = document.createElement('span');
    badge.className = 'gallery-slot-badge';
    input.insertAdjacentElement('afterend', badge);
    badge.insertAdjacentElement('afterend', button);
    button.addEventListener('click', () => state.open(index));
    return index + 1;
  }

  function sync(form) {
    form.querySelectorAll('input[type="hidden"][name="reference_sources"]').forEach(node => node.remove());
    const inputs = [...form.querySelectorAll('input[type="file"][name="reference_images"]:not(:disabled)')];
    for (const input of inputs) {
      const picked = input.dataset.galleryJobId;
      const hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = 'reference_sources';
      hidden.value = picked ? 'gallery:' + picked : 'upload';
      form.appendChild(hidden);
    }
  }

  function paint(input, character) {
    const badge = input.parentElement.querySelector('.gallery-slot-badge');
    if (character) {
      input.dataset.galleryJobId = character.job_id;
      if (badge) {
        badge.textContent = character.name || 'Saved character';
        badge.classList.add('is-set');
      }
      input.value = '';
    } else {
      delete input.dataset.galleryJobId;
      if (badge) { badge.textContent = ''; badge.classList.remove('is-set'); }
    }
  }

  function mount(form) {
    const inputs = [...form.querySelectorAll('input[type="file"][name="reference_images"]')];
    if (!inputs.length || form.dataset.gallerySlotPicker === 'on') return;
    form.dataset.gallerySlotPicker = 'on';

    const dialog = document.createElement('dialog');
    dialog.className = 'gallery-dialog';
    dialog.innerHTML = '<div class="gallery-head"><strong>Your characters</strong>' +
      '<button type="button" class="btn gallery-close" aria-label="Close">✕</button></div>' +
      '<div class="gallery-grid"></div>';
    document.body.appendChild(dialog);
    const grid = dialog.querySelector('.gallery-grid');

    let target = null;
    const state = {
      async open(index) {
        target = inputs[index];
        grid.textContent = 'Loading…';
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
        try {
          const response = await fetch('/api/characters/library', {headers: {Accept: 'application/json'}});
          const data = response.ok ? await response.json() : {characters: []};
          const characters = Array.isArray(data.characters) ? data.characters : [];
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
            card.setAttribute('aria-pressed', 'false');
            const image = document.createElement('img');
            image.src = character.image_url;
            image.alt = character.name || 'Saved character';
            image.loading = 'lazy';
            const label = document.createElement('span');
            label.textContent = character.name || 'Untitled character';
            card.append(image, label);
            card.addEventListener('click', () => {
              paint(target, character);
              sync(form);
              dialog.close();
            });
            grid.appendChild(card);
          }
        } catch (error) {
          grid.textContent = 'The character library could not be read.';
        }
      },
    };

    inputs.forEach((input, index) => mountSlot(form, input, index, state));
    dialog.querySelector('.gallery-close').addEventListener('click', () => dialog.close());
    form.addEventListener('change', event => {
      if (event.target.matches('input[type="file"][name="reference_images"]')) {
        paint(event.target, null);
        sync(form);
      }
    });
    // A slot can be enabled after this script runs; the form must still describe every
    // slot it is about to send, so the list is rebuilt at submit time too.
    form.addEventListener('submit', () => sync(form), true);
    const linked = new URLSearchParams(location.search).get('character_id');
    if (linked && /^[a-f0-9]{32}$/.test(linked)) {
      const first = inputs[0];
      paint(first, {job_id: linked, name: 'Chosen character'});
    }
    sync(form);
  }

  function boot() { document.querySelectorAll('form').forEach(mount); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  else boot();
})();

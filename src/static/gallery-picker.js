/* Choose a saved character for a reference slot.

   This is a chooser, not a second reference path: it hands the character id to the
   existing handoff, which fetches the PNG, writes a real File into the slot and
   dispatches `change` so the page repaints its own picker. */
import {applyCharacterReference} from '/static/character-handoff.js';

(() => {
  'use strict';

  function toast() {
    const region = document.getElementById('h3-toast-region') || document.getElementById('toast-region');
    return message => window.OpenGenjutsuStudio?.showToast?.(region, message);
  }

  function linkFor(jobId) {
    const params = new URLSearchParams(location.search);
    params.set('character_id', jobId);
    return '?' + params.toString();
  }

  async function choose(input, jobId) {
    return applyCharacterReference({search: linkFor(jobId), input, notify: toast()});
  }

  function card(character, close) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'gallery-card';
    const image = document.createElement('img');
    image.src = character.image_url;
    image.alt = character.name || 'Saved character';
    image.loading = 'lazy';
    const label = document.createElement('span');
    label.textContent = character.name || 'Untitled character';
    button.append(image, label);
    return button;
  }

  function mount(form) {
    const inputs = [...form.querySelectorAll('input[type="file"][name="reference_images"]')];
    if (!inputs.length || form.dataset.galleryChooser === 'on') return;
    form.dataset.galleryChooser = 'on';

    const dialog = document.createElement('dialog');
    dialog.className = 'gallery-dialog';
    dialog.innerHTML = '<div class="gallery-head"><strong>Your characters</strong>' +
      '<button type="button" class="btn gallery-close" aria-label="Close">✕</button></div>' +
      '<div class="gallery-grid"></div>';
    document.body.appendChild(dialog);
    const grid = dialog.querySelector('.gallery-grid');
    const close = () => dialog.close();
    dialog.querySelector('.gallery-close').addEventListener('click', close);

    inputs.forEach(input => {
      if (input.disabled) return;
      const label = form.querySelector(`label[for="${input.id}"]`);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn gallery-open';
      button.textContent = 'From gallery';
      (label || input).insertAdjacentElement('afterend', button);
      button.addEventListener('click', async () => {
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
            const item = card(character, close);
            item.addEventListener('click', async () => {
              if (await choose(input, character.job_id)) close();
            });
            grid.appendChild(item);
          }
        } catch (error) {
          grid.textContent = 'The character library could not be read.';
        }
      });
    });
  }

  function boot() { document.querySelectorAll('form').forEach(mount); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  else boot();
})();

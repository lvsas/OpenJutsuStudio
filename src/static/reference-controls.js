(() => {
  const primaryInput = document.querySelector('#reference');
  const secondaryInput = document.querySelector('#reference-2');
  const secondaryTarget = document.querySelector('#reference-target-2');
  const secondary = document.querySelector('#second-reference');
  const toggle = document.querySelector('#add-second-reference');
  const urls = { primary: null, secondary: null };

  function release(slot) {
    if (urls[slot]) URL.revokeObjectURL(urls[slot]);
    urls[slot] = null;
  }

  function reset(slot) {
    const suffix = slot === 'secondary' ? '-2' : '';
    const thumb = document.querySelector(`#reference-thumb${suffix}`);
    thumb.replaceChildren('＋');
    document.querySelector(`#reference-file-name${suffix}`).textContent = slot === 'secondary'
      ? 'Add the second character'
      : 'Add a clear character image';
  }

  function preview(input, slot) {
    const file = input.files[0];
    if (!file) return;
    release(slot);
    urls[slot] = URL.createObjectURL(file);
    const suffix = slot === 'secondary' ? '-2' : '';
    const image = Object.assign(document.createElement('img'), { src: urls[slot], alt: '' });
    document.querySelector(`#reference-thumb${suffix}`).replaceChildren(image);
    document.querySelector(`#reference-file-name${suffix}`).textContent = file.name;
  }

  function setSecondReference(visible) {
    secondary.hidden = !visible;
    secondaryInput.disabled = !visible;
    secondaryTarget.disabled = !visible;
    toggle.setAttribute('aria-expanded', String(visible));
    toggle.lastElementChild.textContent = visible ? 'Remove second character' : 'Add a second character';
    toggle.firstElementChild.textContent = visible ? '−' : '＋';
    if (visible) return;
    secondaryInput.value = '';
    secondaryTarget.value = '';
    release('secondary');
    reset('secondary');
  }

  primaryInput.addEventListener('change', () => preview(primaryInput, 'primary'));
  secondaryInput.addEventListener('change', () => preview(secondaryInput, 'secondary'));
  toggle.addEventListener('click', () => setSecondReference(secondary.hidden));
  window.addEventListener('beforeunload', () => {
    release('primary');
    release('secondary');
  });
})();

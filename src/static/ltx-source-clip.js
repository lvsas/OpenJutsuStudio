// The same local excerpt controller as H3; no upload or compute on selection.
import {SourceClip} from './source-clip.js';
const byId = id => document.getElementById(id);
const input = byId('video'), media = byId('source-preview');
let originalUrl = null;
const changed = () => window.dispatchEvent(new CustomEvent('opengenjutsu:clip-change'));
const clip = new SourceClip({
  root: byId('source-clip'), start: byId('clip-start'), end: byId('clip-end'),
  preview: byId('clip-preview'), status: byId('clip-status'), summary: byId('clip-summary'),
  limit: byId('clip-limit'), media, onChange: changed,
  onPreview: () => {
    const file = input.files[0];
    if (!file || clip.locked) return;
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    originalUrl = URL.createObjectURL(file);
    clip.select(file, originalUrl);
    media.src = originalUrl;
    media.load();
    window.dispatchEvent(new CustomEvent('opengenjutsu:select-stage', {detail: {stage: 'source'}}));
  },
});
window.OpenGenjutsuClip = clip;
clip.setLimit(window.OpenGenjutsuStudio.clipLimit);
const selectSource = () => {
  if (input.disabled) return;
  clip.select(input.files[0], media.getAttribute('src'));
  changed();
};
// Let the existing source owner assign its blob URL before binding metadata.
input.addEventListener('change', () => queueMicrotask(selectSource));
if (input.files[0]) selectSource();
window.addEventListener('beforeunload', () => {
  if (originalUrl) URL.revokeObjectURL(originalUrl);
});
changed();

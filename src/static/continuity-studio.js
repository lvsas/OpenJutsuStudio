/* Native Take recovery only. No render submission or eager media-editor startup. */
import {validCharacterId} from './character-handoff.js';
const byId = id => document.getElementById(id);
const storeKey = 'opengenjutsu.timeline.native-take';
const validId = id => typeof id === 'string' && /^[a-f0-9]{32}$/.test(id);
let entries = [], active = null, epoch = 0, loading = false;
const video = byId('native-video');
const capsule = byId('native-capsule');
function notice(message = '') {
  byId('native-error').textContent = message;
  byId('native-error').hidden = !message;
}
async function getJSON(url) {
  const response = await fetch(url, {credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(20000)});
  if (!response.ok) throw new Error(response.status === 409
    ? 'This native take could not be verified. Its source files have not been changed.'
    : 'Native takes could not be loaded. Refresh to try again.');
  return response.json();
}
function remembered() { try { return localStorage.getItem(storeKey); } catch { return null; } }
function drawShelf() {
  const list = byId('native-takes'); list.replaceChildren();
  if (!entries.length) {
    const text = document.createElement('p'); text.className = 'microcopy';
    text.textContent = 'No native takes have been recovered here yet. An imported MP4 alone is not a continuable take.';
    list.append(text); return;
  }
  for (const entry of entries) {
    const record = entry.take, button = document.createElement('button');
    button.type = 'button'; button.className = 'native-choice'; button.dataset.takeId = record.take_id;
    button.setAttribute('aria-pressed', String(active?.take.take_id === record.take_id));
    const name = document.createElement('strong'); name.textContent = 'Recovered H3 take';
    const info = document.createElement('small');
    info.textContent = `${record.family.context.delivered_frames} frames · ${record.take_id.slice(0,8)}`;
    button.append(name, info); button.addEventListener('click', () => choose(entry)); list.append(button);
  }
}
async function inspect() {
  if (!active || !capsule.open) return;
  const token = epoch, entry = active;
  byId('native-capsule-json').textContent = 'Reading the public capsule…';
  try {
    const data = await getJSON(entry.capsule_url);
    if (token !== epoch || !capsule.open) return;
    byId('native-capsule-json').textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    if (token === epoch && capsule.open) byId('native-capsule-json').textContent = error.message;
  }
}
function choose(entry) {
  ++epoch; active = entry; notice();
  const record = entry.take, context = record.family.context;
  try { localStorage.setItem(storeKey, record.take_id); } catch { /* Recovery still works without local storage. */ }
  byId('native-title').textContent = 'Recovered H3 take';
  byId('native-geometry').textContent = `${context.width} × ${context.height} · ${context.delivered_frames} frames · ${context.fps} fps`;
  byId('native-state').textContent = 'MCTX + COND recorded · validated when the preview is read';
  const parent = record.lineage.parent_id;
  byId('native-lineage').textContent = parent
    ? `${record.lineage.relation || 'Parent recorded'} · external parent ${parent.slice(0,12)}…`
    : 'No parent recorded';
  byId('native-recipe').textContent = record.recipe.availability === 'captured_execution_graph'
    ? 'Execution graph captured · model/seed identity unresolved'
    : 'Execution graph unavailable';
  byId('native-compatibility').textContent = 'Unverified — no replay or continuation claim';
  byId('native-status').textContent = 'Loading a metadata-stripped preview. The native family remains unchanged.';
  byId('native-empty').hidden = true;
  video.hidden = false; video.pause(); video.dataset.takeId = record.take_id;
  video.src = entry.media_url; video.load();
  const link = byId('native-capsule-download'); link.href = entry.capsule_url + '?download=true'; link.hidden = false;
  byId('native-capsule-json').textContent = 'Open to inspect this take’s public capsule.';
  drawShelf(); if (capsule.open) inspect();
}
async function refresh() {
  if (loading) return;
  loading = true; byId('native-refresh').disabled = true; notice();
  try {
    const data = await getJSON('/api/continuity/takes');
    if (!Array.isArray(data.takes)) throw new Error('The native take response was invalid.');
    for (const entry of data.takes) {
      const id = entry.take?.take_id;
      if (!validId(id) || entry.media_url !== `/api/continuity/takes/${id}/media`
          || entry.capsule_url !== `/api/continuity/takes/${id}/capsule`)
        throw new Error('The native take response was invalid.');
    }
    entries = data.takes;
    const wanted = active?.take.take_id || remembered();
    const selected = entries.find(entry => entry.take.take_id === wanted) || entries[0];
    if (selected) choose(selected);
    else {
      ++epoch; active = null; video.pause(); video.removeAttribute('src'); video.load(); video.hidden = true;
      byId('native-empty').hidden = false;
      byId('native-title').textContent = 'Select a native take';
      for (const id of ['native-geometry','native-state','native-lineage','native-recipe']) byId(id).textContent = '—';
      byId('native-capsule-download').hidden = true;
      byId('native-capsule-json').textContent = 'Select a take to inspect its public capsule.';
      byId('native-status').textContent = 'No generation starts on this page.';
      drawShelf();
    }
  } catch (error) { notice(error.message); }
  finally { loading = false; byId('native-refresh').disabled = false; }
}
video.addEventListener('loadedmetadata', () => {
  if (active && video.readyState >= 1 && new URL(video.currentSrc,location.href).pathname === active.media_url)
    byId('native-status').textContent = 'Recovered preview · native states stay attached to this take.';
});
video.addEventListener('error', () => {
  if (active && video.getAttribute('src') === active.media_url)
    byId('native-status').textContent = 'Preview unavailable. Refresh this take to retry; no raw native file is substituted.';
});
capsule.addEventListener('toggle', inspect);
byId('native-refresh').addEventListener('click', refresh);
let editorLoaded = false;
byId('supporting-tools').addEventListener('toggle', async event => {
  if (!event.currentTarget.open || editorLoaded) return;
  editorLoaded = true;
  try { await import('./timeline.js'); }
  catch { editorLoaded = false; notice('Supporting media tools could not be loaded. Refresh the page to retry.'); }
});
const params = new URLSearchParams(location.search), character = params.get('character_id');
if (params.getAll('character_id').length === 1 && validCharacterId(character)) {
  const image = byId('native-character-image');
  image.addEventListener('load', () => { byId('native-character').hidden = false; });
  image.addEventListener('error', () => notice('The linked character reference is unavailable. Your native take was not changed.'));
  image.src = `/api/characters/jobs/${character}/image`;
}
refresh();

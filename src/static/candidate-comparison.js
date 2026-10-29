/* Read-only comparison: one explicit, lazy player, never a sequence selection. */
import {exactSeed} from './sequence-state.js';
const validId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
function requestSeeds(body) {
  if (typeof body !== 'string') return [];
  // JSON.parse validates syntax/shape only; never use its rounded seed Numbers.
  const parsed = JSON.parse(body);
  if (!parsed || Array.isArray(parsed) || !Array.isArray(parsed.seeds)) return [];
  // Tokenize strings atomically (including escaped quotes), then inspect only
  // top-level member keys. Prompt text and nested objects cannot supply seeds.
  const tokens = body.match(/"(?:\\[\s\S]|[^"\\])*"|[{}\[\],:]|[^\s{}\[\],:"]+/g);
  let depth = 0, seeds = null;
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (depth === 1 && token.startsWith('"') && tokens[i + 1] === ':' && JSON.parse(token) === 'seeds') {
      if (seeds !== null || tokens[i + 2] !== '[') throw new Error('Ambiguous seed list.');
      seeds = tokens.slice(i + 3, tokens.indexOf(']', i + 3))
        .filter(value => value !== ',').map(value => exactSeed(value));
    }
    if (token === '{' || token === '[') depth++;
    if (token === '}' || token === ']') depth--;
  }
  return seeds?.length === parsed.seeds.length ? seeds : [];
}
export function candidateSeed(candidate, index, frozen = {}) {
  // The API emits uint64 JSON integers. response.json() may already have rounded
  // them. Prefer the original literal request (same ordered candidates), never
  // stringify an unsafe Number and present it as an exact seed.
  try {
    const seeds = requestSeeds(frozen.body);
    if (Number.isInteger(index) && index >= 0 && seeds[index] != null) return seeds[index];
  } catch { /* Legacy recovery can lack the original literal request. */ }
  try {
    if (typeof candidate.seed === 'string') return exactSeed(candidate.seed);
    if (Number.isSafeInteger(candidate.seed) && candidate.seed >= 0) return exactSeed(String(candidate.seed));
  } catch { /* Do not invent provenance for invalid or rounded values. */ }
  return 'unavailable (exact value not provided)';
}
export function mountCandidateComparison({player, panel, label, message, close,onPreview=()=>{},onClear=()=>{}}) {
  let attemptId = null, candidates = [], frozen = {}, selected = null,returnTo=null;
  player.preload = 'none'; player.controls = true; player.playsInline = true;
  player.autoplay = false;
  const clear = () => {
    selected = null; player.pause(); player.removeAttribute('src'); player.load();
    panel.hidden = true; label.textContent = ''; message.textContent = '';onClear();
  };
  function preview(index,{returnTo:origin=null}={}) {
    const candidate = candidates[index];
    if (!candidate || candidate.status !== 'done' || !validId(candidate.take_id)) return;
    returnTo=origin;
    const source = `/api/continuity/takes/${candidate.take_id}/media`;
    if (selected !== candidate.take_id) {
      player.pause(); selected = candidate.take_id; player.src = source; player.load();
      message.textContent = 'Use Play to inspect video and any recorded audio. Preview does not keep this take.';
    }
    label.textContent = `Candidate ${index + 1} · Seed ${candidateSeed(candidate, index, frozen)}`;
    panel.hidden = false;onPreview();player.focus();
  }
  player.addEventListener('error', () => {
    if (selected && player.getAttribute('src') === `/api/continuity/takes/${selected}/media`)
      message.textContent = 'Preview unavailable. Close and preview again to retry. Your takes and setup are unchanged; Keep remains a separate choice.';
  });
  close.addEventListener('click', ()=>{const origin=returnTo;clear();returnTo=null;if(origin?.isConnected!==false)origin?.focus();});
  return {preview, clear,
    update(view, context) {
      if (attemptId !== view.attempt_id) clear();
      attemptId = view.attempt_id; candidates = view.candidates; frozen = context;
      if (selected && !candidates.some(c => c.status === 'done' && c.take_id === selected)) clear();
    },
  };
}

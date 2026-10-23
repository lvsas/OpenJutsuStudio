/* Read-only comparison: one explicit, lazy player, never a sequence selection. */
import {exactSeed} from './sequence-state.js';
const validId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
export function candidateSeed(candidate, index, frozen = {}) {
  // The API emits uint64 JSON integers. response.json() may already have rounded
  // them. Prefer the original literal request (same ordered candidates), never
  // stringify an unsafe Number and present it as an exact seed.
  try {
    const match = typeof frozen.body === 'string'
      && frozen.body.match(/"seeds"\s*:\s*\[([0-9,\s]*)\]\s*}$/);
    if (match) {
      const seeds = match[1].split(',').map(value => exactSeed(value.trim()));
      const parsed = JSON.parse(frozen.body);
      if (Array.isArray(parsed.seeds) && parsed.seeds.length === seeds.length && seeds[index] != null)
        return seeds[index];
    }
  } catch { /* Legacy recovery can lack the original literal request. */ }
  try {
    if (typeof candidate.seed === 'string') return exactSeed(candidate.seed);
    if (Number.isSafeInteger(candidate.seed) && candidate.seed >= 0) return exactSeed(String(candidate.seed));
  } catch { /* Do not invent provenance for invalid or rounded values. */ }
  return 'unavailable (exact value not provided)';
}
export function mountCandidateComparison({player, panel, label, message, close}) {
  let attemptId = null, candidates = [], frozen = {}, selected = null;
  player.preload = 'none'; player.controls = true; player.playsInline = true;
  player.autoplay = false;
  const clear = () => {
    selected = null; player.pause(); player.removeAttribute('src'); player.load();
    panel.hidden = true; label.textContent = ''; message.textContent = '';
  };
  function preview(index) {
    const candidate = candidates[index];
    if (!candidate || candidate.status !== 'done' || !validId(candidate.take_id)) return;
    const source = `/api/continuity/takes/${candidate.take_id}/media`;
    if (selected !== candidate.take_id) {
      player.pause(); selected = candidate.take_id; player.src = source; player.load();
      message.textContent = 'Use Play to inspect video and any recorded audio. Preview does not keep this take.';
    }
    label.textContent = `Candidate ${index + 1} · Seed ${candidateSeed(candidate, index, frozen)}`;
    panel.hidden = false; player.focus();
  }
  player.addEventListener('error', () => {
    if (selected && player.getAttribute('src') === `/api/continuity/takes/${selected}/media`)
      message.textContent = 'Preview unavailable. Close and preview again to retry. Your takes and setup are unchanged; Keep remains a separate choice.';
  });
  close.addEventListener('click', clear);
  return {preview, clear,
    update(view, context) {
      if (attemptId !== view.attempt_id) clear();
      attemptId = view.attempt_id; candidates = view.candidates; frozen = context;
      if (selected && !candidates.some(c => c.status === 'done' && c.take_id === selected)) clear();
    },
  };
}

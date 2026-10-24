// H3-only same-origin transport. No model hosts, credentials or remote assets.
export const byId = id => document.getElementById(`h3-${id}`);
export const validId = id => typeof id === 'string' && /^[a-f0-9]{32}$/.test(id);
export function jobURL(id, suffix = '') {
  if (!validId(id)) throw new Error('Invalid H3 job identifier. Check the server response.');
  return `/api/jobs/${encodeURIComponent(id)}${suffix}`;
}
export function h3URL(id, suffix) {
  jobURL(id);
  return `/api/h3/jobs/${encodeURIComponent(id)}${suffix}`;
}
// The comparison reel is engine-agnostic: the same route serves LTX and H3 jobs.
export function revealURL(id) {
  jobURL(id);
  return `/api/jobs/${encodeURIComponent(id)}/reveal`;
}
export async function request(url, options = {}) {
  let response;
  try {
    const signal = options.signal || (!options.method || options.method === 'GET' ? AbortSignal.timeout(20000) : undefined);
    response = await fetch(url, {credentials: 'same-origin', ...options, signal});
  } catch {
    throw new Error('Connection interrupted. Check the studio service, then retry status before submitting again.');
  }
  let data;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const detail = Array.isArray(data?.detail)
      ? data.detail.map(item => `${item.loc?.slice(1).join('.') || 'input'}: ${item.msg}`).join('; ')
      : typeof data?.detail === 'string' ? data.detail : 'Check the studio service and selected inputs.';
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }
  if (!data || typeof data !== 'object') throw new Error('Invalid JSON response. Check the studio service.');
  return data;
}
const STAGE_LABELS = {empty: 'Awaiting media', source: 'Source preview', reference: 'Reference', result: 'Result ready'};

// Same contract as the LTX studio: one stage state drives the frame and its badge.
export function setStage(mode) {
  const current = Object.hasOwn(STAGE_LABELS, mode) ? mode : 'empty';
  byId('stage-empty').hidden = current !== 'empty';
  for (const kind of ['source', 'reference', 'result']) {
    const media=byId(`${kind}-preview`);
    media.hidden=kind!==current;
    if(kind!==current&&kind!=='reference')media.pause?.();
  }
  const inspection=byId('inspection-status');
  if(inspection)inspection.hidden=true;
  byId('state').textContent = STAGE_LABELS[current];
  return current;
}

// Only explicit inspection changes scroll/focus; restoring a take never does.
export function inspectTakeStage(kind, secondReference=false) {
  if(!['source','reference','result'].includes(kind))return false;
  const media=byId(kind==='reference'?`take-reference${secondReference?'-2':''}-preview`:`${kind}-preview`);
  const status=byId('inspection-status');
  if(!media?.getAttribute('src')) {
    status.textContent='This saved preview is unavailable. Retry status; the take is unchanged.';
    status.hidden=false;return false;
  }
  if(kind==='reference')byId('reference-preview').src=media.src;
  setStage(kind);
  for(const card of document.querySelectorAll('[data-h3-stage]')) {
    const matches=card.dataset.h3Stage===kind&&(kind!=='reference'||(card.id==='h3-take-reference-2-card')===secondReference);
    card.setAttribute('aria-pressed',String(matches));
  }
  status.textContent=kind==='reference'?`Saved reference ${secondReference?'2':'1'}`:kind==='source'?'Saved source video':'Saved H3 result';
  status.hidden=false;
  const frame=byId('inspection-preview');
  frame.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
  frame.focus({preventScroll:true});
  return true;
}

// The frame and the capsule card both show the same stage, as LTX does: the card
// keeps a thumbnail of the media that the take actually consumed.
export function loadStageMedia(kind, url) {
  for (const id of [`${kind}-preview`, `take-${kind}-preview`]) {
    const media = byId(id);
    if (!media || media.getAttribute('src') === (url || null)) continue;
    if (media.tagName === 'VIDEO') media.pause();
    if (url) media.src = url;
    else media.removeAttribute('src');
    if (media.tagName === 'VIDEO') media.load();
  }
}

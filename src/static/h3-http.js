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
export function showMedia(kind, url, missing = '') {
  const media = byId(`${kind}-preview`), empty = byId(`${kind}-empty`);
  if (media.getAttribute('src') !== url) {
    if (media.tagName === 'VIDEO') media.pause();
    if (url) media.src = url;
    else media.removeAttribute('src');
    if (media.tagName === 'VIDEO') media.load();
  }
  media.hidden = !url;
  empty.hidden = !!url;
  if (missing) empty.textContent = missing;
}

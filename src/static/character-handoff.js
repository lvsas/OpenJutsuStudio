/* ID-only handoff: selecting a kept character never submits a GPU job. */
export const validCharacterId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);

export async function applyCharacterReference({search = location.search, input, fetcher = fetch,
                                                notify = () => {}, isBusy = () => false} = {}) {
  const params = new URLSearchParams(search);
  const id = params.get('character_id');
  if (id === null) return false;
  if (params.getAll('character_id').length !== 1 || !validCharacterId(id)) {
    notify('The character link is invalid. Choose a character from your library.');
    return false;
  }
  if (!input || input.files?.length || input.disabled || isBusy()) {
    notify('Your current reference was kept. Open the character again when the studio is idle.');
    return false;
  }
  try {
    const response = await fetcher(`/api/characters/jobs/${id}/image`, {
      credentials: 'same-origin', signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error('This character is no longer available. Return to Characters to choose another.');
    if (!/^image\/png(?:;|$)/i.test(response.headers.get('Content-Type') || '')) {
      throw new Error('The character image response was invalid. Your reference was not changed.');
    }
    const maxBytes = 32 * 1024 * 1024;
    const statedSize = Number(response.headers.get('Content-Length'));
    if (statedSize > maxBytes) throw new Error('The character image exceeds the reference transfer budget. Download it from Characters.');
    // Bound the actual body too: Content-Length is advisory, not a size guarantee.
    const reader = response.body?.getReader();
    if (!reader) throw new Error('The character image could not be read.');
    const chunks = [];
    let length = 0;
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > maxBytes) throw new Error('The character image exceeds the reference transfer budget. Download it from Characters.');
        chunks.push(value);
      }
    } finally { await reader.cancel().catch(() => {}); }
    if (!length) throw new Error('The character image was empty.');
    // Never overwrite a manual choice or a job that became active during the GET.
    if (input.files?.length || input.disabled || isBusy()) {
      notify('Your newer reference was kept. The character was not substituted.');
      return false;
    }
    const file = new File(chunks, `character-${id.slice(0, 8)}.png`, {type: 'image/png'});
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles: true}));
    notify('Character reference added. Choose a source video when you are ready.');
    return true;
  } catch (error) {
    notify(error?.message || 'The character could not be transferred. Your current inputs were kept.');
    return false;
  }
}

export function bootstrapCharacterHandoff() {
  const h3 = document.documentElement.dataset.engine === 'h3';
  const prefix = h3 ? 'h3-' : '';
  const input = document.getElementById(`${prefix}reference`);
  const region = document.getElementById(`${prefix}toast-region`);
  return applyCharacterReference({input, notify: message => {
    window.OpenGenjutsuStudio?.showToast?.(region, message);
  }});
}

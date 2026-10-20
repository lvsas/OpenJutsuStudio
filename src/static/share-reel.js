/* One preview-first share experience for both studios. No network publishing integration. */
(() => {
  'use strict';
  const CAPTION = 'Same moment. New character. Made with OpenGenjutsu. #OpenGenjutsu #CharacterSwap';
  const MAX_SHARE_BYTES = 100 * 1024 * 1024;
  const cache = new Map();
  let dialog, ui, epoch = 0, opener = null, current = null, shareFile = null;

  function createDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.className = 'share-reel-dialog';
    dialog.setAttribute('aria-labelledby', 'share-reel-title');
    dialog.innerHTML = `
      <div class="share-reel-header">
        <div><p class="eyebrow">OPEN<span>GENJUTSU</span> / CHARACTER SWAP</p>
        <h2 id="share-reel-title">Your moment. Ready to share.</h2></div>
        <button type="button" class="btn btn-ghost share-reel-close" aria-label="Close reel preview" autofocus>×</button>
      </div>
      <div class="share-reel-layout">
        <div class="share-reel-screen" aria-busy="true">
          <video class="share-reel-video" controls playsinline loop muted preload="metadata" hidden aria-label="Your share reel"></video>
          <div class="share-reel-placeholder"><span class="share-reel-orb" aria-hidden="true"></span>
            <p class="share-reel-build-copy">Preparing your share reel…</p></div>
        </div>
        <div class="share-reel-tools">
          <section class="share-reel-passport" aria-label="Take Passport">
            <p class="eyebrow">TAKE PASSPORT</p><h3>Your character.<br> Your moment.</h3>
            <p>Same performance. A new identity. Made with OpenGenjutsu.</p>
          </section>
          <p class="share-reel-status" role="status" aria-live="polite">Preparing your share reel…</p>
          <button type="button" class="btn btn-secondary share-reel-retry" hidden>Try again</button>
          <div class="share-reel-actions" hidden>
            <button type="button" class="btn btn-primary share-reel-native" hidden>Share reel</button>
            <a class="btn btn-primary share-reel-download" download>Download reel</a>
          </div>
          <p class="share-reel-help">Download the reel, then add it to your social app. No post is published automatically.</p>
          <label class="field-label" for="share-reel-caption">A caption to make it yours</label>
          <textarea id="share-reel-caption" class="text-input share-reel-caption" rows="3" maxlength="1000"></textarea>
          <button type="button" class="btn btn-secondary share-reel-copy">Copy caption</button>
          <a class="share-reel-original" download>Download full result instead</a>
          <button type="button" class="btn btn-ghost share-reel-done">Back to my swap</button>
        </div>
      </div>`;
    document.body.append(dialog);
    const q = name => dialog.querySelector(`.share-reel-${name}`);
    ui = Object.fromEntries(['close', 'screen', 'video', 'placeholder', 'build-copy', 'status', 'retry',
      'actions', 'native', 'download', 'help', 'caption', 'copy', 'original', 'done'].map(name => [name, q(name)]));
    ui.close.addEventListener('click', () => dialog.close());
    ui.done.addEventListener('click', () => dialog.close());
    ui.retry.addEventListener('click', () => {
      if (!current) return;
      cache.delete(current.jobId);
      prepare(current, ++epoch, true);
    });
    ui.video.addEventListener('error', () => {
      if (dialog.open && !ui.video.hidden) ui.status.textContent = 'Preview could not play. You can still download the reel, or try again.';
    });
    ui.copy.addEventListener('click', async () => {
      const token = epoch;
      try {
        await navigator.clipboard.writeText(ui.caption.value);
        if (token === epoch) ui.status.textContent = 'Caption copied. Add your reel in your social app.';
      } catch {
        if (token !== epoch) return;
        ui.caption.focus();
        ui.caption.select();
        ui.status.textContent = 'Clipboard unavailable. Your caption is selected — copy it manually.';
      }
    });
    ui.native.addEventListener('click', async () => {
      if (!shareFile || !current) return;
      const token = epoch;
      ui.native.disabled = true;
      try {
        // File already prepared: keep the native call inside the explicit user gesture.
        await navigator.share({files: [shareFile], title: 'My OpenGenjutsu Swap', text: ui.caption.value});
        if (token === epoch) ui.status.textContent = 'Returned from your device’s share sheet.';
      } catch (error) {
        if (token === epoch) ui.status.textContent = error.name === 'AbortError'
          ? 'Sharing cancelled. Your reel is still here.'
          : 'File sharing is unavailable here. Download the reel and copy your caption instead.';
      } finally {
        if (token === epoch) ui.native.disabled = false;
      }
    });
    dialog.addEventListener('click', event => { if (event.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
    }});
    dialog.addEventListener('close', () => {
      // The close event is queued: close() followed synchronously by open() must not let the
      // previous session's teardown erase the preview that is already on screen.
      if (dialog.open) return;
      epoch += 1;
      ui.video.pause();
      ui.video.removeAttribute('src');
      ui.video.load();
      shareFile = null;
      document.body.classList.remove('share-reel-open');
      if (opener?.isConnected) opener.focus({preventScroll: true});
    });
  }

  function safeURL(value, jobId, artifactId, kind, attachment = false) {
    if (typeof value !== 'string') throw new Error('Invalid reel manifest.');
    const url = new URL(value, location.origin);
    const base = `/api/jobs/${jobId}/reels/${artifactId}`;
    if (url.origin !== location.origin || url.pathname !== base + (kind === 'media' ? '/media' : '')
        || (attachment && url.searchParams.get('download') !== 'true')) throw new Error('Invalid reel manifest.');
    return url.pathname + url.search;
  }

  async function requestManifest(url, options) {
    const response = await fetch(url, {...options, signal: AbortSignal.timeout(30000)});
    const payload = await response.json();
    if (!response.ok) throw new Error(response.status === 429
      ? 'The reel studio is busy. Your result is safe — try again shortly.'
      : 'Your reel could not be prepared. Your full result is still available.');
    return payload;
  }

  async function buildManifest(jobId, retry) {
    let payload = await requestManifest(`/api/jobs/${encodeURIComponent(jobId)}/reveal?layout=social${retry ? '&retry=true' : ''}`, {method: 'POST'});
    const started = Date.now();
    const artifactId = payload.artifact_id;
    if (!/^[a-f0-9]{64}$/.test(artifactId || '')) throw new Error('Invalid reel manifest.');
    while (payload.status === 'queued' || payload.status === 'running') {
      if (Date.now() - started > 12 * 60 * 1000) throw new Error('The reel is taking longer than expected. Close this preview and try again to check it.');
      const statusURL = safeURL(payload.status_url, jobId, artifactId, 'status');
      await new Promise(resolve => setTimeout(resolve, 1500));
      payload = await requestManifest(statusURL);
    }
    if (payload.status === 'error') throw new Error('Your reel could not finish. Try again, or download your full result.');
    if (payload.status !== 'ready' || payload.artifact_id !== artifactId || payload.job_id !== jobId
        || payload.layout !== 'social' || typeof payload.renderer_version !== 'string'
        || !/^[A-Za-z0-9_.-]+\.mp4$/.test(payload.filename || '')) throw new Error('Invalid reel manifest.');
    return {...payload, preview_url: safeURL(payload.preview_url, jobId, artifactId, 'media'),
      download_url: safeURL(payload.download_url, jobId, artifactId, 'media', true)};
  }

  function manifest(jobId, retry = false) {
    if (!cache.has(jobId)) {
      const pending = buildManifest(jobId, retry);
      cache.set(jobId, pending);
      pending.catch(() => { if (cache.get(jobId) === pending) cache.delete(jobId); });
      if (cache.size > 8) cache.delete(cache.keys().next().value);
    }
    return cache.get(jobId);
  }

  async function prepareFile(data, token) {
    if (!navigator.share || !navigator.canShare || typeof File === 'undefined') return;
    try {
      const probe = new File([''], data.filename, {type: 'video/mp4'});
      if (!navigator.canShare({files: [probe]})) return;
      const response = await fetch(data.preview_url);
      if (!response.ok) return;
      const length = Number(response.headers.get('content-length'));
      if (!length || length > MAX_SHARE_BYTES) return;
      const blob = await response.blob();
      if (!blob.size || blob.size > MAX_SHARE_BYTES || token !== epoch || !dialog.open) return;
      const file = new File([blob], data.filename, {type: 'video/mp4'});
      if (!navigator.canShare({files: [file]})) return;
      shareFile = file;
      ui.native.hidden = false;
      ui.native.disabled = false;
      ui.download.classList.replace('btn-primary', 'btn-secondary');
      ui.help.textContent = 'Share opens your device’s share sheet. Or download the MP4 and post it yourself.';
    } catch { /* A download remains available even if native file sharing is unsupported. */ }
  }

  async function prepare(options, token, retry = false) {
    ui.video.pause();
    ui.video.removeAttribute('src');
    ui.video.hidden = true;
    ui.placeholder.hidden = false;
    ui.actions.hidden = true;
    ui.native.hidden = true;
    ui.retry.hidden = true;
    shareFile = null;
    ui.download.removeAttribute('href');
    ui.download.classList.replace('btn-secondary', 'btn-primary');
    ui.screen.setAttribute('aria-busy', 'true');
    ui['build-copy'].textContent = 'Preparing your share reel…';
    ui.status.textContent = 'Making your before-and-after reel. Your full result is safe.';
    ui.help.textContent = 'Download the reel, then add it to your social app. No post is published automatically.';
    try {
      const data = await manifest(options.jobId, retry);
      if (token !== epoch || !dialog.open) return;
      ui.video.src = data.preview_url;
      ui.video.hidden = false;
      ui.placeholder.hidden = true;
      ui.download.href = data.download_url;
      ui.download.download = data.filename;
      ui.actions.hidden = false;
      ui.status.textContent = 'Watch your swap, then make it yours.';
      ui.screen.setAttribute('aria-busy', 'false');
      ui.video.load();
      ui.video.play().catch(() => { /* Playback controls are always available. */ });
      prepareFile(data, token);
    } catch (error) {
      if (token !== epoch || !dialog.open) return;
      ui['build-copy'].textContent = 'Your result is safe.';
      ui.status.textContent = error.message || 'Unable to prepare the reel. Please try again.';
      ui.retry.hidden = false;
      ui.screen.setAttribute('aria-busy', 'false');
    }
  }

  function open(options) {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(options?.jobId || '')) throw new Error('Invalid take identifier.');
    const original = new URL(options.resultUrl, location.origin);
    if (original.origin !== location.origin || original.pathname !== `/api/jobs/${options.jobId}/result`) throw new Error('Invalid result URL.');
    createDialog();
    opener = options.returnFocus || document.activeElement;
    current = {...options};
    ui.caption.value = options.caption || CAPTION;
    ui.original.href = original.pathname + '?download=true';
    if (!dialog.open) dialog.showModal();
    document.body.classList.add('share-reel-open');
    prepare(current, ++epoch);
  }
  window.OpenGenjutsuShare = Object.freeze({open});
})();

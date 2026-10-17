import {byId, validId, jobURL, h3URL, request, revealURL, showMedia} from './h3-http.js';
const STORAGE_KEY = 'opengenjutsu.h3.current-job';
const TERMINAL = new Set(['done', 'error', 'failed', 'cancelled']);
const STAGES = {h3_prepare: 'Preparing source and reference', h3_submitting: 'H3 submission / inference',
  h3_assemble: 'Assembling result and preserving audio', done: 'H3 take complete', h3_error: 'H3 take failed'};
// Grounded in the frozen recipe: this studio runs MiniMax H3 with its Character Swap LoRA.
const CAPTION = 'Made with OpenGenjutsu — an open-source local video transformation studio, recast with MiniMax H3 and its Character Swap LoRA.';

function saveCapsule(capsule, id) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(capsule, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = `h3-take-${id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadReel(url, id) {
  const link = document.createElement('a');
  link.href = `${url}?download=true`;
  link.download = `opengenjutsu-h3-${id}-comparison.mp4`;
  link.click();
}

function elapsedText(job) {
  if (!job) return '';
  const start = job.status === 'queued' ? job.created : job.started || job.created;
  const end = TERMINAL.has(job.status) ? job.finished : Date.now() / 1000;
  const seconds = Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, Math.floor(end - start)) : null;
  return seconds === null ? '' : `${job.status === 'queued' ? 'Queue wait' : 'Elapsed'}: ${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export class H3Take {
  constructor(onActivity, checkReady, onStage) {
    this.onActivity = onActivity;
    this.checkReady = checkReady;
    this.onStage = onStage;
    this.epoch = 0;
    this.active = false;
    byId('save-capsule').addEventListener('click', () => { if (this.capsule) saveCapsule(this.capsule, this.id); });
    byId('replay').addEventListener('click', () => this.replay());
    // Shared result actions: the same generic comparison-reel contract LTX uses.
    byId('build-reel').addEventListener('click', () => this.reel());
    byId('copy-caption').addEventListener('click', () => this.copyCaption());
    setInterval(() => this.timer(), 1000);
  }
  storage(id) {
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch { /* Status still works when browser persistence is unavailable. */ }
  }
  resume() {
    let id = this.id;
    try { id ||= localStorage.getItem(STORAGE_KEY); } catch { /* Private browser. */ }
    if (validId(id)) this.watch(id);
    else if (id) this.storage(null);
  }
  reset() {
    this.epoch += 1;
    clearTimeout(this.pollTimer);
    this.id = this.job = this.capsule = null;
    this.storage(null);
    this.setActive(false);
    this.clearResult();
    byId('state').textContent = 'Awaiting media';
    byId('stage').textContent = 'Ready for your inputs';
    byId('status').textContent = 'No take submitted.';
    byId('timer').textContent = '';
  }
  clearResult() {
    this.capsule = null;
    byId('result-actions').hidden = true;
    byId('capsule-details').hidden = true;
    byId('capsule-manifest').textContent = '';
    byId('save-capsule').disabled = byId('replay').disabled = true;
    byId('build-reel').disabled = true;
    byId('download').removeAttribute('href');
    showMedia('result', '', 'Available after completion.');
  }
  setActive(active) {
    this.active = active;
    this.onActivity(active);
  }
  watch(id) {
    jobURL(id);
    this.epoch += 1;
    clearTimeout(this.pollTimer);
    this.id = id;
    this.job = null;
    this.clearResult();
    showMedia('source', '', 'Loading this take’s source…');
    showMedia('reference', '', 'Loading this take’s reference…');
    this.storage(id);
    this.setActive(true);
    this.onStage?.('source');
    byId('state').textContent = 'Checking job';
    byId('stage').textContent = 'Checking persisted H3 status';
    byId('timer').textContent = '';
    byId('status').textContent = 'Reading persisted H3 job status…';
    this.poll(this.epoch);
  }
  async poll(epoch) {
    try {
      const job = await request(jobURL(this.id));
      if (epoch !== this.epoch) return;
      if (job.engine !== 'minimax-h3' || job.id !== this.id) {
        this.storage(null);
        this.setActive(false);
        throw new Error('The saved job is not an H3 take. Select H3 inputs to start a new take.');
      }
      if (!['queued', 'running', ...TERMINAL].includes(job.status)) throw new Error('Unknown H3 job state. Retry status.');
      this.job = job;
      this.render(job);
      if (TERMINAL.has(job.status)) {
        this.setActive(false);
        if (job.status === 'done') await this.loadCapsule(epoch);
      } else this.pollTimer = setTimeout(() => this.poll(epoch), 2000);
    } catch (error) {
      if (epoch !== this.epoch) return;
      byId('status').textContent = `${error.message} Use “retry status”; a disconnected request does not stop a job.`;
      byId('status').setAttribute('role', 'alert');
    }
  }
  render(job) {
    byId('state').textContent = job.status;
    byId('stage').textContent = job.status === 'queued' ? 'Waiting in the H3 queue' : STAGES[job.step] || job.step || job.status;
    byId('status').setAttribute('role', job.status === 'error' || job.status === 'failed' ? 'alert' : 'status');
    byId('status').textContent = job.error || (job.status === 'running'
      ? 'Processing. Stage labels come from the worker; no estimated progress is shown.' : `H3 job ${job.id}: ${job.status}.`);
    showMedia('source', h3URL(job.id, '/source'), 'Source preview unavailable. Retry status.');
    showMedia('reference', h3URL(job.id, '/reference'), 'Reference preview unavailable. Retry status.');
    if (job.status === 'done') {
      showMedia('result', jobURL(job.id, '/result'));
      byId('download').href = jobURL(job.id, '/result');
      byId('result-actions').hidden = false;
      byId('build-reel').disabled = false;
      this.onStage?.('result');
    }
    this.timer();
  }
  timer() {
    byId('timer').textContent = elapsedText(this.job);
  }
  async loadCapsule(epoch) {
    byId('capsule-status').textContent = 'Checking the frozen recipe…';
    try {
      const capsule = await request(h3URL(this.id, '/capsule'));
      if (epoch !== this.epoch) return;
      if (capsule.engine !== 'minimax-h3' || capsule.job_id !== this.id) throw new Error('Capsule identity mismatch.');
      this.capsule = capsule;
      byId('capsule-manifest').textContent = JSON.stringify(capsule, null, 2);
      byId('capsule-details').hidden = false;
      byId('save-capsule').disabled = false;
      byId('replay').disabled = !this.ready || this.active;
      this.onActivity(this.active);
      byId('capsule-status').textContent = 'Frozen H3 recipe and fingerprints verified by the studio. Replay checks local input bytes.';
    } catch (error) {
      if (epoch === this.epoch) byId('capsule-status').textContent = `Capsule unavailable: ${error.message} Retry status to check again.`;
    }
  }
  async copyCaption() {
    try {
      await navigator.clipboard.writeText(CAPTION);
      byId('capsule-status').textContent = 'Caption copied. Add your downloaded result before posting.';
    } catch {
      byId('capsule-status').textContent = 'Clipboard access was unavailable. Copy the caption manually.';
    }
  }
  async reel() {
    if (!validId(this.id)) return;
    byId('build-reel').disabled = true;
    byId('build-reel').textContent = 'Building reel…';
    try {
      const payload = await request(revealURL(this.id), {method: 'POST'});
      downloadReel(payload.reveal_url, this.id);
      byId('capsule-status').textContent = 'Your local 9:16 comparison reel is downloading.';
    } catch (error) {
      byId('capsule-status').textContent = error.message;
    } finally {
      byId('build-reel').disabled = !this.job || this.job.status !== 'done';
      byId('build-reel').textContent = 'Build comparison reel';
    }
  }
  async replay() {
    if (!this.capsule || this.active) return;
    this.setActive(true);
    byId('replay').disabled = true;
    try {
      if (!await this.checkReady()) throw new Error('H3 is not ready. Resolve the availability notes above.');
      const response = await request(h3URL(this.id, '/replay'), {method: 'POST'});
      this.watch(response.job_id);
    } catch (error) {
      byId('capsule-status').textContent = `Replay not started: ${error.message}`;
      this.setActive(false);
      byId('replay').disabled = !this.ready;
    }
  }
}

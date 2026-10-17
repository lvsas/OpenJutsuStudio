import {byId, validId, jobURL, h3URL, request, revealURL, setStage, loadStageMedia} from './h3-http.js';
const STORAGE_KEY = 'opengenjutsu.h3.current-job';
const TERMINAL = new Set(['done', 'error', 'failed', 'cancelled']);
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

function toast(message, type = 'error') {
  window.OpenGenjutsuStudio?.showToast?.(document.getElementById('h3-toast-region'), message, type);
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
    byId('run-overlay').hidden = true;
  }
  clearResult() {
    this.capsule = null;
    byId('result-actions').hidden = true;
    byId('capsule-details').hidden = true;
    byId('capsule-manifest').textContent = '';
    byId('save-capsule').disabled = byId('replay').disabled = true;
    byId('build-reel').disabled = true;
    byId('download').removeAttribute('href');
    byId('take-story').hidden = true;
    loadStageMedia('result', '');
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
    loadStageMedia('source', '');
    loadStageMedia('reference', '');
    this.storage(id);
    this.setActive(true);
    this.onStage?.('source');
    byId('run-overlay').hidden = false;
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
      toast(`${error.message} A disconnected request does not stop a job.`);
    }
  }
  render(job) {
    window.OpenGenjutsuStudio?.renderProgress?.(job, 'h3-');
    byId('run-overlay').hidden = TERMINAL.has(job.status);
    // Same as LTX: a failed take is announced, not only written to the status line.
    if (job.status === 'error' || job.status === 'failed') toast(job.error || 'This take could not finish.');
    loadStageMedia('source', h3URL(job.id, '/source'));
    loadStageMedia('reference', h3URL(job.id, '/reference'));
    if (job.status === 'done') {
      loadStageMedia('result', jobURL(job.id, '/result'));
      byId('download').href = jobURL(job.id, '/result');
      byId('result-actions').hidden = false;
      byId('build-reel').disabled = false;
      // Same as LTX: the capsule describes a take, so it appears with the take.
      byId('take-story').hidden = false;
      this.onStage?.('result');
    }
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
      const link = document.createElement('a');
      link.href = `${payload.reveal_url}?download=true`;
      link.download = `opengenjutsu-h3-${this.id}-comparison.mp4`;
      link.click();
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

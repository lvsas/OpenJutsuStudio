import {byId, validId, jobURL, h3URL, request, loadStageMedia} from './h3-http.js';
const STORAGE_KEY = 'opengenjutsu.h3.current-job';
const TERMINAL = new Set(['done', 'error', 'failed', 'cancelled']);
const COMPLETED_KEY = 'opengenjutsu.h3.completed-job';
const CAPTION = 'Same moment. New character. Made with OpenGenjutsu. #OpenGenjutsu #CharacterSwap';

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
    this.lastCompletedId = this.storage(undefined, COMPLETED_KEY);
    if (!validId(this.lastCompletedId)) this.lastCompletedId = null;
    byId('return-last').addEventListener('click', () => this.restoreCompleted());
    byId('save-capsule').addEventListener('click', () => { if (this.capsule) saveCapsule(this.capsule, this.id); });
    byId('replay').addEventListener('click', () => this.replay());
    // Shared result actions: the same generic comparison-reel contract LTX uses.
    byId('build-reel').addEventListener('click', () => this.reel());
    byId('copy-caption').addEventListener('click', () => this.copyCaption());
  }
  storage(id, key = STORAGE_KEY) {
    try {
      if (id === undefined) return localStorage.getItem(key);
      if (id) localStorage.setItem(key, id);
      else localStorage.removeItem(key);
    } catch { /* Status still works when browser persistence is unavailable. */ }
  }
  returnAffordance() {
    byId('return-last').hidden = !this.lastCompletedId || !byId('result-actions').hidden;
    byId('return-last').disabled = this.active;
  }
  resume() {
    const id = this.id || this.storage();
    if (validId(id)) this.watch(id);
    else { this.storage(null); this.restoreCompleted(); }
    this.returnAffordance();
  }
  validate(job, id) {
    if (job.engine !== 'minimax-h3' || job.id !== id) throw new Error('The saved job is not an H3 take.');
    if (!['queued', 'running', ...TERMINAL].includes(job.status)) throw new Error('Unknown H3 job state.');
    if (job.status === 'done' && job.result_url !== jobURL(id, '/result')) throw new Error('This take has no available result.');
  }
  async resultAvailable(job) {
    const response = await fetch(job.result_url, {headers: {Range: 'bytes=0-0'}, signal: AbortSignal.timeout(20000)});
    await response.body?.cancel();
    if (!response.ok) throw new Error('The saved result is no longer available.');
  }
  async restoreCompleted() {
    const id = this.lastCompletedId;
    if (!validId(id) || this.active) return;
    const epoch = ++this.epoch;
    try {
      const job = await request(jobURL(id));
      this.validate(job, id);
      if (job.status !== 'done') throw new Error('The saved swap has no completed result.');
      await this.resultAvailable(job);
      if (epoch !== this.epoch) return;
      this.id = id; this.job = job;
      this.render(job);
      await this.loadCapsule(epoch);
    } catch (error) {
      if (epoch === this.epoch) { toast(error.message); this.returnAffordance(); }
    }
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
    this.returnAffordance();
  }
  setActive(active) {
    this.active = active;
    this.onActivity(active);
    this.returnAffordance();
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
    loadStageMedia('reference-2', '');
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
      try { this.validate(job, this.id); }
      catch (error) { this.storage(null); this.setActive(false); byId('run-overlay').hidden = true; throw error; }
      if (job.status === 'done') {
        try { await this.resultAvailable(job); }
        catch (error) {
          if (epoch !== this.epoch) return;
          this.storage(null); this.setActive(false); byId('run-overlay').hidden = true; throw error;
        }
        if (epoch !== this.epoch) return;
      }
      this.job = job;
      this.render(job);
      if (TERMINAL.has(job.status)) {
        this.setActive(false);
        this.storage(null);
        if (job.status === 'done') await this.loadCapsule(epoch);
      } else this.pollTimer = setTimeout(() => this.poll(epoch), 2000);
    } catch (error) {
      if (epoch !== this.epoch) return;
      if (/^HTTP (404|410):/.test(error.message)) {
        this.storage(null); this.setActive(false); byId('run-overlay').hidden = true;
      }
      toast(`${error.message} A disconnected request does not stop a job.`);
      if (this.active) this.pollTimer = setTimeout(() => this.poll(epoch), 3000);
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
      this.lastCompletedId = job.id;
      this.storage(job.id, COMPLETED_KEY);
      loadStageMedia('result', jobURL(job.id, '/result'));
      byId('download').href = `${job.result_url}?download=true`;
      const timelineLink = byId('open-timeline');
      if (timelineLink) timelineLink.href = `/timeline?job_id=${job.id}`;
      byId('result-actions').hidden = false;
      byId('build-reel').disabled = false;
      byId('completion-more').open = byId('take-inspection').open = false;
      this.returnAffordance();
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
      // A reopened take shows every reference it consumed, not just the first.
      if (capsule.recipe.reference_count > 1) {
        loadStageMedia('reference-2', h3URL(this.id, '/reference/1'));
      } else loadStageMedia('reference-2', '');
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
  reel() {
    if (!validId(this.id) || this.job?.status !== 'done' || byId('result-actions').hidden) return;
    if (!window.OpenGenjutsuShare?.open) return toast('Share preview is unavailable. Reload the studio to retry.');
    window.OpenGenjutsuShare.open({jobId: this.id, resultUrl: this.job.result_url, returnFocus: byId('build-reel'), caption: CAPTION});
  }
  async replay() {
    if (!this.capsule || this.active) return;
    const epoch = ++this.epoch;
    this.setActive(true);
    byId('replay').disabled = true;
    try {
      const ready = await this.checkReady();
      if (epoch !== this.epoch) return;
      if (!ready) throw new Error('H3 is not ready. Resolve the availability notes above.');
      const response = await request(h3URL(this.id, '/replay'), {method: 'POST'});
      if (epoch !== this.epoch) return;
      this.watch(response.job_id);
    } catch (error) {
      if (epoch !== this.epoch) return;
      byId('capsule-status').textContent = `Replay not started: ${error.message}`;
      this.setActive(false);
      byId('replay').disabled = !this.ready;
    }
  }
}
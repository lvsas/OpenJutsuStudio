// Local, non-destructive draft selection. Never probes/uploads or starts compute.
export class SourceClip {
  constructor({root, start, end, preview, status, summary, limit, media, maxSeconds = 15, onChange, onPreview}) {
    Object.assign(this, {root, start, end, preview, status, summary, limit, media, onChange, onPreview});
    this.locked = false;
    this.epoch = 0;
    this.state = 'empty';
    this.duration = null;
    this.range = ['', ''];
    this.listeners = [];
    this.configuredMax = Number.isFinite(maxSeconds) && maxSeconds > 0 ? maxSeconds : 15;
    this.setLimit(undefined);
    for (const input of [start, end]) for (const event of ['input', 'change']) {
      input.addEventListener(event, () => {
        if (!this.locked && this.needsExcerpt) {
          this.range = [start.value, end.value];
          this.stopPreview();
        }
        this.render();
        this.onChange?.();
      });
    }
    preview.addEventListener('click', () => this.play());
    this.render();
  }
  setLimit(value) {
    const known = Number.isFinite(value) && value > 0;
    this.supported = known;
    this.maxSeconds = known ? Math.min(value, this.configuredMax) : this.configuredMax;
    this.limit.textContent = `Max ${this.maxSeconds} s per swap`;
    this.render();
  }
  select(file, url) {
    if (this.locked || (file === this.file && url === this.url)) return;
    this.stopPreview();
    for (const [name, fn] of this.listeners) this.media.removeEventListener(name, fn);
    this.listeners = [];
    const preserve = !!file && file === this.file && this.state === 'ready';
    this.file = file;
    this.url = url;
    const epoch = ++this.epoch;
    if (!preserve) {
      this.duration = null;
      this.range = ['', ''];
      this.state = file ? 'pending' : 'empty';
    }
    const current = () => !this.locked && epoch === this.epoch && this.file === file && this.matchesMedia();
    const listen = (name, fn) => {
      this.media.addEventListener(name, fn);
      this.listeners.push([name, fn]);
    };
    const metadata = () => {
      if (!current() || this.state !== 'pending') return;
      const duration = this.media.duration;
      if (Number.isFinite(duration) && duration > 0) {
        this.duration = duration;
        this.range = ['0', String(Math.min(duration, this.maxSeconds))];
        this.state = 'ready';
      } else this.state = 'failed';
      this.render();
      this.onChange?.();
    };
    listen('loadedmetadata', metadata);
    for (const name of ['error', 'abort']) listen(name, () => {
      if (!current()) return;
      this.stopPreview();
      this.state = 'failed';
      this.render();
      this.onChange?.();
    });
    listen('timeupdate', () => {
      if (!current() || !this.previewing) return;
      if (this.media.currentTime >= Number(this.range[1])) {
        this.stopPreview();
        this.media.currentTime = Number(this.range[1]);
      }
    });
    this.render();
    if (this.media.readyState >= 1) metadata();
  }
  matchesMedia() {
    return !!this.file && !!this.url && this.media.getAttribute('src') === this.url && this.media.currentSrc === this.url;
  }
  get error() {
    if (this.state === 'empty') return 'Choose a source video to select an excerpt.';
    if (this.state === 'pending') return 'Reading original duration… If this does not finish, choose a browser-playable MP4.';
    if (this.state !== 'ready') return 'Cannot read this video’s duration. Choose a browser-playable MP4, then select the excerpt again.';
    if (!this.needsExcerpt) return '';
    if (!this.supported) return 'Excerpt processing is not verified yet. Reload the studio before submitting a long video.';
    const [a, b] = this.range;
    const start = Number(a), end = Number(b);
    if (!a.trim() || !b.trim() || !Number.isFinite(start) || !Number.isFinite(end)) return 'Enter finite Start and End times in seconds.';
    if (start < 0 || end <= start) return 'Start must be at least 0 seconds and End must be after Start.';
    if (end > this.duration) return 'End must not exceed the original video duration.';
    if (end - start > this.maxSeconds) return `Select no more than ${this.maxSeconds} seconds for this swap.`;
    return '';
  }
  get needsExcerpt() { return this.state === 'ready' && this.duration > this.maxSeconds; }
  get valid() { return !this.error; }
  validate() {
    if (!this.locked && this.needsExcerpt) this.range = [this.start.value, this.end.value];
    this.render();
    if (!this.valid) this.start.focus();
    return this.valid;
  }
  appendTo(data) {
    if (!this.valid) throw new Error(this.error);
    if (!this.needsExcerpt) {
      data.delete('clip_start_seconds'); data.delete('clip_end_seconds');
      return;
    }
    data.set('clip_start_seconds', this.range[0]);
    data.set('clip_end_seconds', this.range[1]);
  }
  setLocked(locked) {
    if (locked && !this.locked) this.stopPreview();
    this.locked = locked;
    this.render();
  }
  stopPreview() {
    if (this.previewing) this.media.pause();
    this.previewing = false;
  }
  async play() {
    if (this.locked || !this.needsExcerpt || !this.validate()) return;
    this.onPreview?.();
    const epoch = this.epoch;
    // Restoring the draft URL from a saved take can still be loading. Calling
    // play inside this gesture waits for that resource without autoplay on load.
    if (this.media.getAttribute('src') !== this.url) return;
    this.media.currentTime = Number(this.range[0]);
    this.previewing = true;
    try { await this.media.play(); }
    catch {
      if (epoch !== this.epoch || this.locked) return;
      this.stopPreview();
      this.status.textContent = 'Preview could not play. Try Preview excerpt again, or choose a browser-playable MP4.';
    }
  }
  render() {
    if (!this.range) return;
    const error = this.error;
    this.root.hidden = !this.needsExcerpt;
    for (const [index, input] of [this.start, this.end].entries()) {
      if (input.value !== this.range[index]) input.value = this.range[index];
      input.disabled = this.locked || !this.needsExcerpt;
      input.max = this.duration ?? '';
      input.setCustomValidity(error);
      input.setAttribute('aria-invalid', String(this.state === 'ready' && !!error));
    }
    this.preview.disabled = this.locked || !this.needsExcerpt || !!error;
    this.status.textContent = error || 'Excerpt selected. Generate swap confirms this selection.';
    this.summary.textContent = this.duration === null ? 'Original: — · Selected: —'
      : `Original: ${this.duration} s · Selected: ${error ? '—' : `${Number(this.range[1]) - Number(this.range[0])} s`} (${this.range[0]}–${this.range[1]} s)`;
  }
}

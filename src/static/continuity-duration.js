/* Readiness owns engine arithmetic. This picker only curates delivered seconds. */
const targets = [5, 8, 10, 12, 15];
export function createDurationPicker(select, hint) {
  let choices = [], saved = null, locked = false;
  const valid = () => choices.some(item => String(item.raw_frames) === select.value);
  const sync = () => { select.disabled = locked || !choices.length; };
  function placeholder(text, value) {
    const option = new Option(text, String(value));
    option.disabled = true;
    select.replaceChildren(option);select.value = String(value);
  }
  function reset(raw = null) {
    saved = raw;choices = [];
    placeholder('Checking compatible durations…', raw ?? 277);
    hint.textContent = 'Checking which durations keep the next take continuable…';sync();
  }
  function unavailable() {
    choices = [];placeholder('Duration unavailable', saved ?? 277);
    hint.textContent = 'Compatible durations unavailable. Refresh the take or choose another.';sync();
  }
  function ready(result) {
    const options = result.duration_options;
    if (!(result.available ?? result.extend) || !Array.isArray(options) || !options.length || options.some(item =>
      !Number.isSafeInteger(item.raw_frames) || item.raw_frames < 5 || item.raw_frames > 3600 ||
      !Number.isFinite(item.seconds) || item.seconds <= 0)) { unavailable();return; }
    const nearest = seconds => options.reduce((best, item) =>
      Math.abs(item.seconds - seconds) < Math.abs(best.seconds - seconds) ? item : best);
    const chosen = new Map(targets.map(seconds => {const item = nearest(seconds);return [item.raw_frames, item];}));
    const previous = options.find(item => item.raw_frames === saved);
    if (previous) chosen.set(previous.raw_frames, previous);
    choices = [...chosen.values()].sort((a, b) => a.seconds - b.seconds);
    select.replaceChildren(...choices.map(item => new Option(`About ${item.seconds.toFixed(1)} s`, String(item.raw_frames))));
    if (saved !== null && !previous) {
      const option = new Option('Saved duration unavailable · choose another', String(saved));
      option.disabled = true;select.append(option);select.value = String(saved);
    } else select.value = String(previous?.raw_frames ?? nearest(10).raw_frames);
    updateHint();sync();
  }
  function updateHint() {
    hint.textContent = valid()
      ? 'New footage after the handover. Compatible with this take; final duration is measured on the result.'
      : 'The saved duration is not compatible with this take. Choose a duration to continue; your draft is kept.';
  }
  select.addEventListener('input', updateHint);
  return {reset, ready, unavailable, valid, setLocked(value) {locked = value;sync();}};
}

/* Readiness owns engine arithmetic. This picker only curates delivered seconds. */
const targets = [5, 8, 10, 12, 15];
export function createDurationPicker(select, hint) {
  let choices = [], saved = null, locked = false, audioPolicy = '';
  const valid = () => choices.some(item => String(item.raw_frames) === select.value);
  const sync = () => { select.disabled = locked || !choices.length; };
  function placeholder(text, value) {
    const option = new Option(text, String(value));
    option.disabled = true;
    select.replaceChildren(option);select.value = String(value);
  }
  function reset(raw = null) {
    saved = raw;choices = [];audioPolicy = '';
    placeholder('Checking compatible durations…', raw ?? 277);
    hint.textContent = 'Checking which durations keep the next take continuable…';sync();
  }
  function unavailable() {
    choices = [];placeholder('Duration unavailable', saved ?? 277);
    hint.textContent = 'Duration check request failed. Compatible durations unavailable; try checking again. Your draft is kept.';sync();
  }
  function ready(result) {
    const options = result.duration_options;
    audioPolicy = result.audio_policy === 'original-source' ? ' The original soundtrack continues from the source song.'
      : result.audio_policy === 'native-generated' ? ' Audio is generated for this take.' : '';
    if (!(result.available ?? result.extend)) {
      choices=[];placeholder('No compatible duration', saved ?? 277);
      const operation={root:'New take',forward:'Extend',prepend:'Prepend',bridge:'Bridge'}[result.mode]||'Extend';
      const reasons={
        video_only:'This video has no registered saved state. Choose a native take or create a new take from references.',
        unaligned_start:'This exact beginning cannot accept new footage before it. Choose another anchor or start an independent take.',
        audio_window:'The saved audio cannot supply the complete handover. Choose another take or start an independent take.',
        short_source:'This take needs at least 1.7 s of delivered footage for a handover. Choose a longer take.',
        geometry_mismatch:'Use anchors with matching picture sizes and 24 fps timing.',
        target_unavailable:'The compute target could not be checked. Reconnect the target and retry; nothing was submitted.',
        state_unverified:'The saved state could not be verified. Choose another take; nothing was submitted.',
        timing_unavailable:'Saved audio timing is unavailable. Choose another take or start an independent take.',
        audio_phase_conflict:'These anchors have incompatible sound timing. Choose a different pair or start an independent take.',
        source_audio_exhausted:'The original soundtrack ends here. Choose another anchor; no replacement song or silence will be added.',
      };
      hint.textContent=`${operation} unavailable. ${reasons[result.reason_code]||'No compatible duration is available here. Choose another anchor or start an independent take.'}`;
      sync();return;
    }
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
      ? `New footage after the handover. Compatible with this take; final duration is measured on the result.${audioPolicy}`
      : 'The saved duration is not compatible with this take. Choose a duration to continue; your draft is kept.';
  }
  select.addEventListener('input', updateHint);
  return {reset, ready, unavailable, valid, setLocked(value) {locked = value;sync();}};
}

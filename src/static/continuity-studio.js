/* Native sequence workspace; generation only after explicit submission. */
import {validCharacterId} from './character-handoff.js';
import {mountSequence} from './sequence-workspace.js';
import {attemptBody} from './sequence-state.js';
import {createAttemptClient} from './continuity-attempt-client.js';
import {mountCandidateComparison, candidateSeed} from './candidate-comparison.js';
import {createDurationPicker} from './continuity-duration.js';
import {parseProjectContext} from './project-context.js';
import {positionLabel,positionsOf} from './sequence-positions.js';
import {mountPositionGeneration} from './position-generation.js';
const byId = id => document.getElementById(id);
const validId = id => typeof id === 'string' && /^[a-f0-9]{32}$/.test(id);
const duration = createDurationPicker(byId('forward-length'), byId('forward-duration-hint'));
let entries = [], active = null, epoch = 0, loading = false;
let linkedTake=null,handoffStarted=false;
const video = byId('native-video');
const capsule = byId('native-capsule');
function notice(message = '') {
  byId('native-error').textContent = message;
  byId('native-error').hidden = !message;
}
async function getJSON(url) {
  const response = await fetch(url, {credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(20000)});
  if (!response.ok) throw new Error(response.status === 409
    ? 'This native take could not be verified. Its source files have not been changed.'
    : 'Native takes could not be loaded. Refresh to try again.');
  return response.json();
}
let activePlacement = null, canExtend = false, inFlight = false, initialized = false;
let unconfirmed = false, referencesReady = false, selectedPosition = null;
function updateComposer() {
  const locked=inFlight||unconfirmed||!sequence.editable();
  const open=byId('forward-open');
  open.hidden=!!selectedPosition||!active|| (!!activePlacement&&!byId('forward-form').hidden);
  byId('position-setup').disabled=locked;
  open.textContent=activePlacement?'Edit extension setup':'Add to sequence to extend';
  open.disabled=!active||locked;
  byId('forward-submit').disabled=locked||(selectedPosition?!positionComposer.valid():
    !activePlacement||!canExtend||!referencesReady||!duration.valid());
  byId('position-new').disabled=locked;byId('position-character').disabled=locked;
  byId('native-handoff-add').disabled=locked||!linkedTake;byId('native-handoff-new').disabled=locked;
  for(const control of byId('forward-form').querySelectorAll('textarea,input,select'))control.disabled=locked;
  duration.setLocked(locked);
  for(const button of byId('forward-reference-list').querySelectorAll('button'))button.disabled=locked;
}
const sequence = mountSequence({onSelect: showSelection,onLockChange:updateComposer,
  onContextChange:()=>{++epoch;byId('native-handoff').hidden=true;linkedTake=null;notice();},
  onPreview: entry => {showSelection(entry,null,null);if(selectedPosition)showPosition(selectedPosition,sequence.positionDraft());}, onCompose: openForward, onPosition:showPosition, onError: notice});
const positionComposer=mountPositionGeneration({sequence,getJSON,byId,duration,onUpdate:updateComposer,
  onMessage:message=>{byId('forward-state').textContent=message;}});
function showPosition(position,draft=null,{focus=false}={}) {
  ++epoch;selectedPosition=position;
  byId('position-context').hidden=!position;
  byId('position-context').parentElement?.classList.toggle('is-position',!!position);
  if(position) {
    byId('forward-form').hidden=true;
    const placements=sequence.state().placements;
    const take=id=>placements.find(p=>p.placement_id===id)?.take_id.slice(0,8);
    byId('position-title').textContent=positionLabel(position);
    const anchors=position.mode==='root'?'Start from references. No video parent.'
      : position.mode==='prepend'?`Create footage leading into ${take(position.right)}.`
      : position.mode==='bridge'?`Create a connection from ${take(position.left)} to ${take(position.right)}.`
      : `Continue from the saved state of ${take(position.left)}.`;
    byId('position-description').textContent=anchors+' Only Generate starts a run.';
    byId('position-setup').hidden=true;
    byId('position-new').hidden=position.mode==='root';
    byId('position-character').hidden=position.mode!=='root'||byId('native-character').hidden;
    byId('forward-submit').textContent={root:'Generate new take',prepend:'Generate beginning',bridge:'Generate bridge',forward:'Generate extension'}[position.mode];
    byId('composer-anchor').textContent=anchors;
    positionComposer.open(position,draft||sequence.positionDraft()).then(()=>{
      if(focus&&selectedPosition===position){
        byId('position-context').scrollIntoView?.({block:'start',inline:'nearest',behavior:'instant'});
        byId('forward-prompt').focus({preventScroll:true});
      }
    });
  } else {positionComposer.close();byId('forward-submit').textContent='Generate extension';}
  updateComposer();
}
byId('position-setup').addEventListener('click',()=>{
  try{sequence.composePosition();}catch(error){notice(error.message);}
});
byId('position-add').addEventListener('click',()=>sequence.addAtPosition());
byId('position-new').addEventListener('click',()=>sequence.openPosition(selectedPosition,{mode:'root'}));
byId('position-character').addEventListener('click',()=>positionComposer.useCharacter().catch(error=>notice(error.message)));
byId('position-close').addEventListener('click',()=>sequence.clearPosition());
function showSelection(entry, placement, draft) {
  byId('native-handoff').hidden=true;linkedTake=null;
  activePlacement = placement;
  canExtend = false; referencesReady = false;
  byId('forward-prompt').value = draft?.prompt || '';
  byId('forward-seed').value = draft?.seed || '';
  duration.reset(draft?.raw_frames ?? null);
  // Selecting a library preview must expose setup too. Placement and generation
  // stay separate explicit actions, rather than a hidden prerequisite.
  byId('forward-form').hidden = !!selectedPosition || !entry;
  if (!entry) {
    ++epoch; active = null; video.pause(); video.removeAttribute('src'); video.load(); video.hidden = true;
    byId('native-empty').hidden = false;
    byId('native-title').textContent = 'Your next take';
    byId('composer-anchor').textContent = 'Select a take on your sequence to continue it.';
    byId('native-readiness').textContent = '';
    byId('native-status').textContent = 'Nothing is generated by adding or selecting a take.';
    byId('native-capsule-download').hidden = true;
    updateComposer();return;
  }
  choose(entry);
  byId('composer-anchor').textContent = placement
    ? `Extend after ${entry.take.take_id.slice(0,8)} · original unchanged`
    : 'Set up your extension below. Add this take to the sequence before generating; no calculation starts when adding it.';
  updateComposer();
}
async function inspect() {
  if (!active || !capsule.open) return;
  const token = epoch, entry = active;
  byId('native-capsule-json').textContent = 'Reading the public capsule…';
  try {
    const data = await getJSON(entry.capsule_url);
    if (token !== epoch || !capsule.open) return;
    byId('native-capsule-json').textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    if (token === epoch && capsule.open) byId('native-capsule-json').textContent = error.message;
  }
}
function choose(entry) {
  ++epoch; active = entry; notice();
  const token = epoch, record = entry.take, context = record.family.context;
  byId('native-title').textContent = `Take ${record.take_id.slice(0,8)}`;
  byId('native-geometry').textContent = `${context.width} × ${context.height} · ${(context.delivered_frames/context.fps).toFixed(1)} s · ${context.fps} fps`;
  byId('native-state').textContent = 'Checking saved state…';
  byId('native-lineage').textContent = record.lineage.parent_id
    ? `${record.lineage.relation || 'Derived'} · native source ${record.lineage.parent_id.slice(0,12)}…`
    : 'No generative parent recorded';
  byId('native-recipe').textContent = record.recipe.availability === 'captured_execution_graph'
    ? 'Executed recipe captured' : 'Executed recipe unavailable';
  byId('native-compatibility').textContent = 'Runtime replay is not a guarantee of visual continuity.';
  byId('native-status').textContent = 'Loading preview…';
  byId('native-readiness').textContent = 'Verifying the saved take…';
  byId('native-empty').hidden = true;
  video.hidden = false; video.pause(); video.dataset.takeId = record.take_id;
  video.src = entry.media_url; video.load();
  const link = byId('native-capsule-download'); link.href = entry.capsule_url + '?download=true'; link.hidden = false;
  byId('native-capsule-json').textContent = 'Open to inspect the public recipe receipt.';
  if (capsule.open) inspect();
  getJSON(`/api/continuity/takes/${record.take_id}/readiness`).then(result => {
    if (epoch !== token) return;
    canExtend = !!result.extend;
    duration.ready(result);
    byId('native-state').textContent = result.verified ? 'Saved state verified · original files preserved' : 'Saved state could not be verified';
    byId('native-readiness').textContent = result.reason || (activePlacement
      ? 'Ready · saved state verified.' : 'Add to your sequence to extend.');
    updateComposer();
  }).catch(error => {if(epoch===token){duration.unavailable();byId('native-readiness').textContent=error.message;updateComposer();}});
  loadReferences(record.take_id);
}
/* A studio link is an inspection request, never a placement or a computation. */
function showLinkedNative(entry) {
  sequence.preview(entry.take.take_id);linkedTake=entry.take.take_id;
  byId('native-handoff').hidden=false;
  const existing=sequence.state().placements.filter(p=>p.take_id===linkedTake);
  byId('native-handoff-message').textContent='Your Swap and its saved state are ready to inspect. Choose where it belongs; nothing has been added.';
  const add=byId('native-handoff-add');add.hidden=false;
  add.textContent=existing.length===1?'Open placement':existing.length>1?'Add another placement':'Add this take';
  byId('native-handoff-new').hidden=true;updateComposer();
}
async function openLinkedSwap(jobId) {
  const token=epoch,projectId=sequence.state().project_id;
  const current=()=>token===epoch&&projectId===sequence.state().project_id;
  const panel=byId('native-handoff'),choices=byId('native-handoff-choices');
  choices.replaceChildren();byId('native-handoff-add').hidden=true;byId('native-handoff-new').hidden=true;
  try {
    const matches=entries.filter(entry=>entry.take.origin?.source_job===jobId);
    if(matches.length===1){showLinkedNative(matches[0]);return;}
    if(matches.length>1){
      // An origin can publish several families. Recency is not the creator's choice.
      panel.hidden=false;
      byId('native-handoff-message').textContent='This Swap has several saved versions. Choose one to preview; none is added automatically.';
      for(const [index,entry] of matches.entries()){
        const button=document.createElement('button');button.type='button';button.className='btn btn-secondary';
        const c=entry.take.family.context;
        button.textContent=`Preview version ${index+1} · ${(c.delivered_frames/c.fps).toFixed(1)} s`;
        button.addEventListener('click',()=>showLinkedNative(entry));choices.append(button);
      }
      return;
    }
    const response=await fetch(`/api/jobs/${jobId}`,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(20000)});
    if(!current())return;
    if(!response.ok)throw new Error('This linked Swap is unavailable. Choose a saved take or start a New take; your project is unchanged.');
    const job=await response.json();if(!current())return;
    if(job.id!==jobId||job.status!=='done'||!['ltx25-ripple','minimax-h3'].includes(job.engine)
        ||job.result_url!==`/api/jobs/${jobId}/result`)
      throw new Error('This linked Swap has no verified completed video. Choose a saved take or return to the studio.');
    showSelection(null,null,null);
    video.hidden=false;byId('native-empty').hidden=true;video.src=job.result_url;video.load();
    byId('native-title').textContent='Swap video';byId('native-geometry').textContent='Video only';
    byId('native-state').textContent='No registered native saved state for this Swap.';
    byId('native-lineage').textContent='No native parent available';byId('native-recipe').textContent='Inspect its recipe in the source studio';
    byId('native-capsule-json').textContent='This video has no registered native Take receipt.';
    byId('native-capsule').open=false;
    byId('native-status').textContent='Video-only preview · no native continuation is implied.';
    byId('native-handoff-message').textContent='Video only — no registered native saved state. Inspect your Swap here, or create an independent New take from references. Nothing was imported or added.';
    panel.hidden=false;byId('native-handoff-new').hidden=false;
  } catch(error){if(current())notice(error.message||'The linked Swap could not be opened. Your project is unchanged.');}
}
byId('native-handoff-add').addEventListener('click',async()=>{
  if(!linkedTake||!sequence.editable()||inFlight||unconfirmed)return;
  try {
    const matches=sequence.state().placements.filter(p=>p.take_id===linkedTake);
    if(matches.length===1)sequence.openPlacement(matches[0].placement_id);
    else sequence.place(linkedTake);
    await sequence.flush();byId('native-handoff').hidden=true;linkedTake=null;
  }catch(error){notice(error.message);}
});
byId('native-handoff-new').addEventListener('click',()=>{
  if(!sequence.editable()||inFlight||unconfirmed)return;
  sequence.openPosition(positionsOf(sequence.state()).at(-1),{mode:'root'});
  byId('native-handoff').hidden=true;
});

async function refresh() {
  if (loading) return;
  loading = true; byId('native-refresh').disabled = true; notice();
  try {
    const data = await getJSON('/api/continuity/takes');
    if (!Array.isArray(data.takes)) throw new Error('The native take response was invalid.');
    for (const entry of data.takes) {
      const id = entry.take?.take_id;
      if (!validId(id) || entry.media_url !== `/api/continuity/takes/${id}/media`
          || entry.capsule_url !== `/api/continuity/takes/${id}/capsule`)
        throw new Error('The native take response was invalid.');
    }
    entries = data.takes;
    if (!initialized) { await sequence.init(entries); initialized = true; }
    else sequence.refresh(entries);
    const context=sequence.editable()?parseProjectContext(location.search):{};
    if(context.job_id&&!handoffStarted&&sequence.editable()){handoffStarted=true;void openLinkedSwap(context.job_id);}
  } catch (error) { notice(error.message); }
  finally { loading = false; byId('native-refresh').disabled = false;updateComposer(); }
}
video.addEventListener('loadedmetadata', () => {
  if (active && video.readyState >= 1 && new URL(video.currentSrc,location.href).pathname === active.media_url)
    byId('native-status').textContent = 'Recovered preview · native states stay attached to this take.';
});
video.addEventListener('error', () => {
  if (active && video.getAttribute('src') === active.media_url)
    byId('native-status').textContent = 'Preview unavailable. Refresh this take to retry; no raw native file is substituted.';
});
capsule.addEventListener('toggle', inspect);
byId('native-refresh').addEventListener('click', refresh);

/* Continuation: one decision, one button, nothing sent before it is asked for. */
const forwardState = message => { byId('forward-state').textContent = message; };
async function openForward() {
  if(!active||inFlight||unconfirmed)return;
  try {
    if(!activePlacement) {
      const draft=draftFields();
      sequence.place(active.take.take_id,draft);await sequence.flush();
    }
    byId('forward-form').hidden=false;updateComposer();
    forwardState('Draft setup only. Generation starts with Generate extension.');
    byId('forward-prompt').focus();
  } catch(error){notice(error.message);}
}
async function loadReferences(takeId) {
  const figure = byId('forward-references'), list = byId('forward-reference-list');
  const token=epoch;referencesReady=false;list.replaceChildren();figure.hidden=false;
  byId('forward-reference-count').textContent=' · checking…';updateComposer();
  try {
    const response = await fetch(`/api/continuity/takes/${takeId}/references`,
      {credentials: 'same-origin', cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if(token!==epoch||active?.take.take_id!==takeId)return;
    if (!response.ok) {
      const hint = document.createElement('span');
      hint.className = 'microcopy';
      hint.textContent = data.detail
        || 'This take does not record a reference. Add one to keep a character.';
      list.append(hint);
      byId('forward-reference-count').textContent = '';
      return;
    }
    const items = Array.isArray(data.references) ? data.references : [];
    referencesReady=true;updateComposer();
    if (!items.length) {
      const hint = document.createElement('span');
      hint.className = 'microcopy';
      hint.textContent = 'No reference recorded for this shot. Add one to keep a character.';
      list.append(hint);
      byId('forward-reference-count').textContent = '';
      return;
    }
    for (const item of items) {
      const holder = document.createElement('span');
      holder.className = 'forward-reference-slot';
      const img = document.createElement('img');
      // Build the URL here rather than trusting a field: a missing one left an
      // <img> with no source, visible as an empty box.
      img.src = `/api/continuity/takes/${takeId}/references/${item.index}`;
      img.alt = `Reference ${item.index}`;
      img.width = 56; img.height = 56;
      img.loading = 'lazy'; img.className = 'forward-reference';
      const drop = document.createElement('button');
      drop.type = 'button'; drop.className = 'forward-reference-drop';
      drop.setAttribute('aria-label', `Remove reference ${item.index}`);
      drop.textContent = '×';
      drop.addEventListener('click', () => changeReference(takeId, item.index, null));
      holder.append(img, drop);
      list.append(holder);
    }
    byId('forward-reference-count').textContent = items.length > 1
      ? ` · ${items.length}` : '';
  } catch {
    if(token!==epoch)return;
    list.textContent='References could not be loaded. Refresh this take to retry.';
    byId('forward-reference-count').textContent=' · unavailable';
  } finally {if(token===epoch)updateComposer();}
}
async function changeReference(takeId, index, file) {
  if(inFlight||unconfirmed){forwardState('Reconnect the saved attempt before editing generation references.');return;}
  try {
    let response;
    if (file) {
      const body = new FormData(); body.append('image', file);
      response = await fetch(`/api/continuity/takes/${takeId}/references`,
        {method: 'POST', body, credentials: 'same-origin'});
    } else {
      response = await fetch(`/api/continuity/takes/${takeId}/references/${index}`,
        {method: 'DELETE', credentials: 'same-origin'});
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      forwardState(data.detail || 'The reference could not be changed.');
      return;
    }
    if(active?.take.take_id===takeId)await loadReferences(takeId);
    forwardState(file ? 'Reference added for the next shot.' : 'Reference removed.');
  } catch { forwardState('The reference could not be changed.'); }
}
byId('forward-reference-input').addEventListener('change', event => {
  const file = event.target.files?.[0];
  event.target.value = '';
  if(file&&selectedPosition)positionComposer.add(file);
  else if (file && active) changeReference(active.take.take_id, 0, file);
});
function closeForward() {
  if(selectedPosition){sequence.clearPosition();return;}
  byId('forward-form').hidden = true;
  updateComposer();
}
byId('forward-open').addEventListener('click', openForward);
byId('forward-cancel').addEventListener('click', closeForward);
/* A draft is local until submitted; submitting freezes exactly what is on screen. */
const draftFields = () => ({
  prompt: byId('forward-prompt').value,
  seed: byId('forward-seed').value.trim(),
  raw_frames: Number(byId('forward-length').value),
});
for (const id of ['forward-prompt', 'forward-seed', 'forward-length','forward-variants']) {
  byId(id).addEventListener('input', () => {
    updateComposer();
    if(selectedPosition){positionComposer.saveFields();return;}
    if (!activePlacement || inFlight) return;
    try { sequence.setDraft(draftFields()); } catch { /* placement changed under the draft */ }
  });
}
const comparison = mountCandidateComparison({player:byId('candidate-video'),
  panel:byId('candidate-preview'), label:byId('candidate-preview-label'),
  message:byId('candidate-preview-message'), close:byId('candidate-preview-close')});
let candidateSignature = '';
function drawCandidates(view, frozen) {
  comparison.update(view, frozen);
  const tray = byId('candidate-tray'), list = byId('candidate-list');
  const done = view.candidates.filter(c => c.status === 'done').length;
  byId('candidate-summary').textContent =
    `${done}/${view.candidates.length} ready · ${view.status}`;
  // Identical polls must not replace focused controls. The shared player lives
  // outside this list and survives progress/status changes as well.
  const signature = JSON.stringify([view, frozen]);
  if (signature === candidateSignature) { tray.hidden = false; return; }
  candidateSignature = signature;
  list.replaceChildren();
  view.candidates.forEach((candidate, index) => {
    const item = document.createElement('li'); item.className = 'candidate';
    const name = document.createElement('strong');
    name.textContent = candidate.status === 'done' ? `Take ${index + 1}` : `Candidate ${index + 1}`;
    const meta = document.createElement('small');
    meta.textContent = candidate.status === 'failed'
      ? `failed · ${candidate.error || 'No result'}`
      : candidate.status === 'running' ? 'Generating…' : candidate.status;
    const seed = document.createElement('small'); seed.className = 'candidate-seed';
    seed.textContent = `Seed ${candidateSeed(candidate, index, frozen)}`;
    item.append(name, meta, seed);
    if (candidate.status === 'done' && validId(candidate.take_id)) {
      const poster = document.createElement('img');
      poster.className = 'candidate-poster'; poster.alt = ''; poster.loading = 'lazy';
      poster.src = `/api/continuity/takes/${candidate.take_id}/poster`;
      const preview = document.createElement('button');
      preview.type = 'button'; preview.className = 'btn btn-secondary';
      preview.textContent = 'Preview video / audio';
      preview.setAttribute('aria-label', `Preview candidate ${index + 1} video and audio`);
      preview.setAttribute('aria-controls', 'candidate-preview');
      preview.addEventListener('click', () => comparison.preview(index));
      const keep = document.createElement('button');
      keep.type = 'button'; keep.className = 'btn btn-primary'; keep.textContent = 'Keep';
      keep.disabled=!['done','failed'].includes(view.status);
      keep.addEventListener('click', async () => {
        keep.disabled = true;
        try {
          const placed = await sequence.insertResult(candidate.take_id, frozen.project_id, frozen.after,frozen.position??null);
          forwardState(placed || 'Return to the original saved sequence to keep this candidate.');
          if (placed) {
            attemptClient.dismiss();comparison.clear();tray.hidden = true;
            byId('forward-variants').value = '1';
            byId('forward-form').hidden = false;updateComposer();
            forwardState('Kept in your sequence. What happens next? Your next generation starts with one take.');
            byId('forward-prompt').focus();
          }
          else keep.disabled=false;
        } catch (error) { forwardState(error.message); keep.disabled = false; }
      });
      item.append(poster, preview, keep);
    }
    list.append(item);
  });
  tray.hidden = false;
}
function recoveryState(state) {
  unconfirmed=state.blocked;inFlight=['sending','running'].includes(state.phase);
  const panel=byId('attempt-recovery');panel.hidden=state.phase==='idle';
  byId('attempt-reconnect').hidden=!['disconnected','not-found','legacy'].includes(state.phase);
  byId('attempt-resubmit').hidden=state.phase!=='not-found';
  byId('attempt-dismiss').hidden=!state.canDismiss;
  const messages={checking:'Reconnecting to the saved attempt…',sending:'Submitting this saved request…',
    running:'Generation is tracked on the server. Reopening this page does not restart it.',
    disconnected:'Connection lost. The original request is kept; no new generation is sent.',
    'not-found':'No saved request found. An explicit retry reuses the exact same request identity.',
    legacy:'Older recovery note: inspect a saved attempt, or clear this note only when all listed work is finished.',
    invalid:'This browser recovery note cannot be read. No request has been sent.',
    terminal:'Saved attempt finished. Results remain recoverable until you keep one or dismiss this note.'};
  byId('attempt-recovery-message').textContent=messages[state.phase]||'';
  const list=byId('attempt-legacy-list');list.replaceChildren();
  if(state.phase==='legacy')for(const view of state.attempts||[]) {
    const row=document.createElement('li'),button=document.createElement('button');
    button.type='button';button.className='btn btn-secondary';
    button.textContent=`Inspect ${view.attempt_id.slice(0,8)} · ${view.status}`;
    button.addEventListener('click',()=>attemptClient.selectLegacy(view.attempt_id).catch(e=>forwardState(e.message)));
    row.append(button);list.append(row);
  }
  updateComposer();
}
const attemptClient=createAttemptClient({onState:recoveryState,onMessage:forwardState,
  onView:async(view,frozen)=>{
    if(view.take_id===active?.take.take_id&&frozen.project_id===sequence.state().project_id
        &&frozen.after===activePlacement?.placement_id&&view.candidates.length>0&&view.candidates.length<=3)
      byId('forward-variants').value=String(view.candidates.length);
    if(view.candidates.some(c=>c.status==='done'))await refresh();
    drawCandidates(view,frozen);
    forwardState(view.status==='running'?'Generating saved candidates…':
      view.status==='pending'?'Queued on the GPU…':view.error||'Saved attempt finished. Inspect its candidates.');
  }});
unconfirmed=attemptClient.blocked();
byId('attempt-reconnect').addEventListener('click',()=>attemptClient.recover());
byId('attempt-resubmit').addEventListener('click',()=>attemptClient.retrySubmission().catch(e=>forwardState(e.message)));
byId('attempt-dismiss').addEventListener('click',()=>{
  try{attemptClient.dismiss();comparison.clear();byId('candidate-tray').hidden=true;forwardState('The browser note was cleared. All takes remain saved.');}
  catch(error){forwardState(error.message);}
});
byId('forward-form').addEventListener('submit', async event => {
  event.preventDefault();
  if(selectedPosition) {
    if(inFlight||unconfirmed||!positionComposer.valid())return;
    try {
      await sequence.flush();const frozen=positionComposer.request();await sequence.flush();
      await attemptClient.submit(frozen);
    } catch(error){forwardState(error.message);}
    return;
  }
  if(!active||!activePlacement||!canExtend||!referencesReady||!duration.valid()||inFlight||unconfirmed)return;
  const fields=draftFields(),count=Number(byId('forward-variants').value)||1;
  const request_id=crypto.randomUUID().replace(/-/g,'');
  const frozen={take_id:active.take.take_id,after:activePlacement.placement_id,
    project_id:sequence.state().project_id};
  try {
    const body=attemptBody({...fields,count,request_id});
    // Save the anchor/project before submission; project_id was previously null
    // when Generate outran the debounced workspace save.
    inFlight=true;updateComposer();
    const saved=await sequence.flush();
    if(active?.take.take_id!==frozen.take_id||activePlacement?.placement_id!==frozen.after
        ||(frozen.project_id&&saved.project_id!==frozen.project_id))
      throw new Error('The selected take changed. Review this draft before generating.');
    comparison.clear();byId('candidate-tray').hidden=true;
    await attemptClient.submit({...frozen,project_id:saved.project_id,request_id,body});
  } catch(error){forwardState(error.message);}
  finally {inFlight=false;unconfirmed=attemptClient.blocked();updateComposer();}
});
window.addEventListener('pagehide',()=>{comparison.clear();attemptClient.dispose();});
let editorLoaded = false;
byId('supporting-tools').addEventListener('toggle', async event => {
  if (!event.currentTarget.open || editorLoaded) return;
  editorLoaded = true;
  try { await import('./timeline.js'); }
  catch { editorLoaded = false; notice('Supporting media tools could not be loaded. Refresh the page to retry.'); }
});
let character=null;
try{character=parseProjectContext(location.search).character_id;}catch(error){notice(error.message);}
if (validCharacterId(character)) {
  const image = byId('native-character-image');
  image.addEventListener('load', () => {
    byId('native-character').hidden = false;
    if(selectedPosition?.mode==='root')byId('position-character').hidden=false;
  });
  image.addEventListener('error', () => notice('The linked character reference is unavailable. Your native take was not changed.'));
  image.src = `/api/characters/jobs/${character}/image`;
}
refresh().then(()=>attemptClient.recover());

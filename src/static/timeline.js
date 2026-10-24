import {apiJSON,validateProject,validId,placements,totalDuration,trimPlacement,movePlacement,formatTime} from './timeline-state.js';
import {SequencePlayer} from './timeline-player.js';
import {getTimelineExport} from './timeline-export-ui.js';
const $=id=>document.getElementById(id);
const json=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const state={project:null,selected:null,busy:false,conflict:false,undo:[],epoch:0,scale:76};
const notify=message=>window.OpenGenjutsuStudio?.showToast?.($('toast-region'),message);
const exportsUI=getTimelineExport(notify);
const player=new SequencePlayer($('timeline-video'),{
  onTime:(time,total)=>{
    $('sequence-seek').value=String(time);$('sequence-time').textContent=`${formatTime(time)} / ${formatTime(total)}`;
    $('playhead').style.left=`${time*state.scale}px`;
  },
  onSelect:clip=>{state.selected=clip.clip_id;paintSelection();},
  onPlayback:playing=>{$('play-sequence').textContent=playing&&player.sequenceMode?'Pause sequence':'Play sequence';},
  onError:message=>{notify(message);$('reload-project').hidden=false;},
});
function remember(id) {try {if (id) localStorage.setItem('opengenjutsu.timeline.project',id);else localStorage.removeItem('opengenjutsu.timeline.project');} catch {}}
function recalled() {try {return localStorage.getItem('opengenjutsu.timeline.project');} catch {return null;}}
function error(message,conflict=false) {
  $('timeline-error').textContent=message;$('timeline-error').hidden=false;
  if (conflict) state.conflict=true;
  $('reload-project').hidden=!state.project;paintLocks();
}
function clearError() {$('timeline-error').hidden=true;$('reload-project').hidden=true;state.conflict=false;}
function paintLocks() {
  const {project,busy,conflict}=state,clips=project?.clips||[];
  $('reload-project').disabled=busy;
  for (const id of ['import-clip','empty-import','new-project','project-picker','refresh-sources','import-file']) $(id).disabled=busy||conflict;
  for (const id of ['project-title','save-title']) $(id).disabled=busy||conflict||!project;
  for (const id of ['trim-start','trim-end','apply-trim','clip-picker','remove-clip']) $(id).disabled=busy||conflict||!clips.length;
  $('undo-edit').disabled=busy||conflict||!state.undo.length;
  const index=clips.findIndex(clip=>clip.clip_id===state.selected);
  $('move-earlier').disabled=busy||conflict||index<=0;
  $('move-later').disabled=busy||conflict||index<0||index>=clips.length-1;
  $('play-sequence').disabled=!clips.length;
  $('sequence-seek').disabled=!clips.length;
  $('export-sequence').disabled=busy||conflict||!clips.length;
  $('save-status').textContent=busy?'Saving…':conflict?'Reload required':project?'All changes saved':'Local workspace';
}
function busy(value) {state.busy=value;paintLocks();}
function selected() {return state.project?.clips.find(clip=>clip.clip_id===state.selected);}
function trimDirty() {
  const clip=selected();return Boolean(clip&&(String(clip.in_frame)!==$('trim-start').value||String(clip.out_frame)!==$('trim-end').value));
}
function allowChange() {
  if (state.busy||state.conflict) return false;
  if (trimDirty()) {notify('Apply your trim first, or restore its frame values before changing clips.');return false;}
  return true;
}
function paintSelection() {
  const clip=selected();$('clip-editor').hidden=!clip;
  for (const element of $('clip-track').children) element.setAttribute('aria-pressed',String(element.dataset.clipId===state.selected));
  if (clip) {
    $('clip-picker').value=clip.clip_id;$('trim-start').value=clip.in_frame;$('trim-end').value=clip.out_frame;
    $('trim-start').max=clip.frames-1;$('trim-end').max=clip.frames;
    $('clip-summary').textContent=`${clip.width}×${clip.height} · ${clip.fps.toFixed(2).replace(/\.00$/,'')} fps`;
    $('trim-help').textContent=`${clip.frames} source frames · ${formatTime((clip.out_frame-clip.in_frame)/clip.fps)} in your cut. End frame is exclusive. The original take stays untouched.`;
  } else $('clip-summary').textContent='No clip selected';
  paintLocks();
}
function paintTrack() {
  const clips=state.project?.clips||[],duration=totalDuration(clips),scale=state.scale;
  $('track-canvas').style.width=`${Math.max($('track-scroll').clientWidth-2,duration*scale)}px`;
  $('clip-track').replaceChildren();$('time-ruler').replaceChildren();$('clip-picker').replaceChildren();
  const step=Math.max(1,Math.ceil(duration/12));
  for (let t=0;t<=Math.max(duration,step);t+=step) {
    const tick=document.createElement('span');tick.textContent=formatTime(t);tick.style.left=`${t*scale}px`;$('time-ruler').append(tick);
  }
  for (const [index,clip] of clips.entries()) {
    const duration=(clip.out_frame-clip.in_frame)/clip.fps;
    const button=document.createElement('button');button.type='button';button.className='timeline-track-clip';
    button.dataset.clipId=clip.clip_id;button.style.width=`${duration*scale}px`;button.title=`${index+1}. ${clip.label} — ${formatTime(duration)}`;
    button.setAttribute('aria-label',`Select clip ${index+1}: ${clip.label}`);
    const label=document.createElement('strong'),detail=document.createElement('small');
    label.textContent=`${String(index+1).padStart(2,'0')} · ${clip.label}`;detail.textContent=formatTime(duration);button.append(label,detail);
    button.addEventListener('click',()=>{if (allowChange()) player.choose(clip.clip_id);});$('clip-track').append(button);
    $('clip-picker').append(new Option(`${index+1}. ${clip.label}`,clip.clip_id));
  }
  $('track-empty').hidden=clips.length>0;$('playhead').hidden=!clips.length;
  $('sequence-seek').max=String(duration||1);$('sequence-summary').textContent=`${clips.length} ${clips.length===1?'clip':'clips'} · ${formatTime(duration)}`;
  paintSelection();
}
function useProject(project,{resetUndo=false}={}) {
  validateProject(project);
  if (resetUndo||state.project?.project_id!==project.project_id) state.undo=[];
  state.project=project;clearError();remember(project.project_id);
  $('project-title').value=project.title;
  $('timeline-empty').hidden=project.clips.length>0;$('timeline-video').hidden=!project.clips.length;
  const params=new URLSearchParams(location.search);params.set('project_id',project.project_id);
  history.replaceState(null,'',`/timeline?${params}`);
  paintTrack();player.setClips(project.clips,state.selected);
  const character=project.character_id;
  $('character-context').hidden=!character;
  if (character) {
    $('context-image').src=`/api/characters/jobs/${character}/image`;
    $('context-ltx').href=`/?character_id=${character}`;$('context-h3').href=`/h3?character_id=${character}`;
  }
  $('project-picker').value=project.project_id;paintLocks();
}
async function refreshProjects() {
  const data=await apiJSON('/api/timeline/projects');
  if (!Array.isArray(data.projects)) throw new Error('The saved sequence list is invalid.');
  const picker=$('project-picker');picker.replaceChildren(new Option('Your sequences',''));
  for (const item of data.projects) if (validId(item.project_id)&&typeof item.title==='string') picker.append(new Option(item.title,item.project_id));
  if (state.project) picker.value=state.project.project_id;
  return data.projects;
}
async function loadProject(id) {
  if (!validId(id)) throw new Error('The saved sequence identifier is invalid.');
  const epoch=++state.epoch;busy(true);
  try {
    const project=await apiJSON(`/api/timeline/projects/${id}`);
    if (epoch===state.epoch) useProject(project,{resetUndo:true});
  } finally {if (epoch===state.epoch) busy(false);}
}
async function ensureProject(characterId=null) {
  if (state.project) return state.project;
  const created=validateProject(await apiJSON('/api/timeline/projects',json({title:'Untitled sequence',...(characterId?{character_id:characterId}:{})})));
  // Read back the exact persisted target before claiming creation succeeded.
  const saved=validateProject(await apiJSON(`/api/timeline/projects/${created.project_id}`));
  useProject(saved,{resetUndo:true});await refreshProjects();return saved;
}
async function mutate(clips,title=$('project-title').value,{record=true}={}) {
  if (!state.project||state.busy||state.conflict) return false;
  const original=state.project,snapshot={title:original.title,clips:placements(original.clips)};busy(true);player.video.pause();
  try {
    await apiJSON(`/api/timeline/projects/${original.project_id}`,{...json({revision:original.revision,title,clips}),method:'PATCH'});
    const saved=validateProject(await apiJSON(`/api/timeline/projects/${original.project_id}`));
    if (record) {state.undo.push(snapshot);if (state.undo.length>20) state.undo.shift();}
    useProject(saved);await refreshProjects();return true;
  } catch(exception) {error(exception.message,exception.status===409||!exception.status);return false;}
  finally {busy(false);}
}
async function addJob(id) {
  if (!validId(id)||!allowChange()) return;
  if (state.project&&$('project-title').value!==state.project.title&&!await mutate(placements(state.project.clips))) return;
  busy(true);
  try {
    const project=await ensureProject();
    const response=validateProject(await apiJSON(`/api/timeline/projects/${project.project_id}/clips`,json({revision:project.revision,job_id:id})));
    const saved=validateProject(await apiJSON(`/api/timeline/projects/${response.project_id}`));
    state.undo.push({title:project.title,clips:placements(project.clips)});state.selected=saved.clips.at(-1)?.clip_id;
    useProject(saved);await refreshProjects();notify('Take added. Your original swap is unchanged.');
    const params=new URLSearchParams(location.search);params.delete('job_id');history.replaceState(null,'',`/timeline?${params}`);
  } catch(exception) {error(exception.message,exception.status===409||!exception.status);}
  finally {busy(false);}
}
async function importFile(file) {
  if (!file||!allowChange()) return;
  if (!/\.mp4$/i.test(file.name)) return notify('Choose an MP4 video for this editing workspace.');
  if (state.project&&$('project-title').value!==state.project.title&&!await mutate(placements(state.project.clips))) return;
  busy(true);player.video.pause();
  try {
    const project=await ensureProject(),body=new FormData();body.append('file',file);body.append('revision',String(project.revision));
    const response=validateProject(await apiJSON(`/api/timeline/projects/${project.project_id}/imports`,{method:'POST',body}));
    const saved=validateProject(await apiJSON(`/api/timeline/projects/${response.project_id}`));
    state.undo.push({title:project.title,clips:placements(project.clips)});state.selected=saved.clips.at(-1)?.clip_id;
    useProject(saved);await refreshProjects();notify('Clip imported. Choose its place in the cut.');
  } catch(exception) {error(exception.message,exception.status===409||!exception.status);}
  finally {busy(false);$('import-file').value='';}
}
async function refreshSources() {
  const host=$('recent-swaps');host.replaceChildren();
  try {
    const response=await fetch('/api/jobs',{credentials:'same-origin',signal:AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error();const jobs=await response.json();if (!Array.isArray(jobs)) throw new Error();
    const candidates=jobs.filter(job=>validId(job.id)&&job.status==='done'&&['minimax-h3','ltx25-ripple'].includes(job.engine)).slice(0,6);
    for (const job of candidates) {
      const button=document.createElement('button');button.type='button';button.className='timeline-source';
      const media=document.createElement('video');media.src=`/api/jobs/${job.id}/result`;media.muted=true;media.preload='metadata';media.playsInline=true;media.setAttribute('aria-hidden','true');
      const copy=document.createElement('span'),label=document.createElement('strong'),detail=document.createElement('small'),add=document.createElement('span');
      copy.className='timeline-source-copy';label.textContent=job.engine==='minimax-h3'?'H3 swap':'LTX swap';detail.textContent=`Take ${job.id.slice(0,8)}`;add.textContent='＋';add.className='timeline-source-add';copy.append(label,detail);button.append(media,copy,add);
      button.addEventListener('click',()=>addJob(job.id));host.append(button);
    }
    if (!candidates.length) {const note=document.createElement('p');note.className='microcopy';note.textContent='Completed swaps appear here. You can also import an MP4.';host.append(note);}
  } catch {const note=document.createElement('p');note.className='microcopy';note.textContent='Recent swaps could not be loaded. Refresh to retry, or import an MP4.';host.append(note);}
}
$('import-clip').addEventListener('click',()=>$('import-file').click());
$('empty-import').addEventListener('click',()=>$('import-file').click());
$('import-file').addEventListener('change',event=>importFile(event.target.files[0]));
for (const event of ['dragenter','dragover']) $('import-clip').addEventListener(event,e=>{e.preventDefault();$('import-clip').classList.add('drag-over');});
for (const event of ['dragleave','drop']) $('import-clip').addEventListener(event,e=>{e.preventDefault();$('import-clip').classList.remove('drag-over');if (event==='drop') importFile(e.dataTransfer?.files[0]);});
$('refresh-sources').addEventListener('click',refreshSources);
$('clip-picker').addEventListener('change',()=>{if (allowChange()) player.choose($('clip-picker').value);else $('clip-picker').value=state.selected;});
$('play-sequence').addEventListener('click',()=>{if (allowChange()) player.playSequence();});
$('sequence-seek').addEventListener('input',event=>{if (allowChange()) player.seek(Number(event.target.value));});
$('timeline-zoom').addEventListener('input',event=>{
  if (trimDirty()) {event.target.value=state.scale;return notify('Apply your trim before changing timeline zoom.');}
  state.scale=Number(event.target.value);paintTrack();player.tick();
});
$('clip-editor').addEventListener('submit',async event=>{
  event.preventDefault();if (state.busy||!state.project) return;
  try {await mutate(trimPlacement(state.project.clips,state.selected,$('trim-start').value,$('trim-end').value));}
  catch(exception) {notify(exception.message);}
});
for (const id of ['trim-start','trim-end']) $(id).addEventListener('input',()=>{player.video.pause();$('save-status').textContent='Trim not applied';});
for (const [id,delta] of [['move-earlier',-1],['move-later',1]]) $(id).addEventListener('click',()=>{if (allowChange()) mutate(movePlacement(state.project.clips,state.selected,delta));});
$('remove-clip').addEventListener('click',()=>{if (allowChange()) mutate(placements(state.project.clips).filter(clip=>clip.clip_id!==state.selected));});
$('undo-edit').addEventListener('click',async()=>{
  if (!allowChange()) return;const snapshot=state.undo.at(-1);if (!snapshot) return;
  if (await mutate(snapshot.clips,snapshot.title,{record:false})) {state.undo.pop();paintLocks();}
});
$('save-title').addEventListener('click',()=>{if (allowChange()&&state.project) mutate(placements(state.project.clips));});
$('export-sequence').addEventListener('click',async()=>{
  if (!allowChange()) return;
  if ($('project-title').value!==state.project.title&&!await mutate(placements(state.project.clips))) return;
  exportsUI.open(state.project);
});
$('reload-project').addEventListener('click',()=>{if (state.project&&!state.busy) loadProject(state.project.project_id).catch(exception=>error(exception.message));});
$('new-project').addEventListener('click',async()=>{
  if (!allowChange()) return;
  if (state.project&&$('project-title').value!==state.project.title) return notify('Save the sequence name before starting another cut.');
  state.project=null;state.selected=null;state.undo=[];history.replaceState(null,'','/timeline');busy(true);
  try {await ensureProject();} catch(exception) {error(exception.message);} finally {busy(false);}
});
$('project-picker').addEventListener('change',()=>{
  if (!allowChange()) {$('project-picker').value=state.project?.project_id||'';return;}
  if (state.project&&$('project-title').value!==state.project.title) {
    $('project-picker').value=state.project.project_id;return notify('Save the sequence name before switching cuts.');
  }
  const id=$('project-picker').value;if (id) loadProject(id).catch(exception=>error(exception.message));
});
window.addEventListener('resize',()=>{if (!trimDirty()) paintTrack();});
window.addEventListener('beforeunload',event=>{
  if (trimDirty()||(state.project&&$('project-title').value!==state.project.title)) {event.preventDefault();event.returnValue='';}
});
async function boot() {
  busy(true);
  const params=new URLSearchParams(location.search),projectId=params.get('project_id');
  // Native references are not instructions to create/import an editing project.
  const nativeView=!!document.getElementById('native-video');
  const jobId=nativeView?null:params.get('job_id'),character=nativeView?null:params.get('character_id');
  for (const key of ['project_id','job_id','character_id']) if (params.has(key)&&(params.getAll(key).length!==1||!validId(params.get(key)))) throw new Error('This workspace link is invalid. Open Timeline from the navigation to start safely.');
  const projects=await refreshProjects();
  if (projectId) await loadProject(projectId);
  else if (character) {busy(true);try {await ensureProject(character);} finally {busy(false);}}
  else {
    const remembered=recalled(),fallback=projects.find(item=>item.project_id===remembered)?.project_id;
    if (fallback) await loadProject(fallback);
  }
  busy(false);
  if (jobId) {
    if (state.project?.clips.some(clip=>clip.source_job_id===jobId)) {
      params.delete('job_id');params.set('project_id',state.project.project_id);history.replaceState(null,'',`/timeline?${params}`);
    } else await addJob(jobId);
  }
  paintLocks();
}
paintTrack();refreshSources();boot().catch(exception=>error(exception.message)).finally(()=>busy(false));

// Pure editor contracts. Browser state is a view; server revisions are authoritative.
export const validId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
const integer = (value, minimum = 0) => Number.isSafeInteger(value) && value >= minimum;
export function validateProject(project) {
  if (!project || !validId(project.project_id) || !integer(project.revision)
      || typeof project.title !== 'string' || project.title.length > 200
      || (project.character_id != null && !validId(project.character_id))
      || !Array.isArray(project.clips) || project.clips.length > 1000) {
    throw new Error('The saved sequence is invalid. Reload it before editing.');
  }
  const seen = new Set();
  for (const clip of project.clips) {
    if (!validId(clip.clip_id) || seen.has(clip.clip_id) || !validId(clip.take_id)
        || typeof clip.label !== 'string' || typeof clip.engine !== 'string'
        || !integer(clip.width, 1) || !integer(clip.height, 1) || !integer(clip.frames, 1)
        || typeof clip.fps !== 'number' || !Number.isFinite(clip.fps) || clip.fps <= 0 || clip.fps > 1000
        || !integer(clip.in_frame) || !integer(clip.out_frame, 1)
        || clip.in_frame >= clip.out_frame || clip.out_frame > clip.frames
        || clip.media_url !== `/api/timeline/takes/${clip.take_id}/media`
        || (clip.source_job_id != null && !validId(clip.source_job_id))) {
      throw new Error('A clip in this sequence is invalid. Your saved media was not changed.');
    }
    seen.add(clip.clip_id);
  }
  return project;
}
export function validateExport(value) {
  const {export_id:id, project_id:project, revision, status} = value || {};
  if (!validId(id) || !validId(project) || !integer(revision)
      || !['queued','running','ready','error'].includes(status)
      || value.status_url !== `/api/timeline/exports/${id}`) throw new Error('Invalid export status.');
  if (status === 'ready') {
    if (value.preview_url !== `/api/timeline/exports/${id}/media`
        || value.download_url !== `/api/timeline/exports/${id}/media?download=true`) {
      throw new Error('The export media link is invalid.');
    }
  } else if (value.preview_url != null || value.download_url != null) {
    throw new Error('The export is not published yet.');
  }
  return value;
}
export const placements = clips => clips.map(({clip_id,in_frame,out_frame}) => ({clip_id,in_frame,out_frame}));
export const totalDuration = clips => clips.reduce((total,clip) => total + (clip.out_frame-clip.in_frame)/clip.fps,0);
export function clipAtTime(clips, value) {
  if (!clips.length) return null;
  const total = totalDuration(clips);
  const time = Math.max(0,Math.min(Number.isFinite(value) ? value : 0,total));
  let offset = 0;
  for (let index=0;index<clips.length;index++) {
    const clip=clips[index], duration=(clip.out_frame-clip.in_frame)/clip.fps;
    if (time < offset+duration || index === clips.length-1) {
      return {index,sourceTime:clip.in_frame/clip.fps+Math.min(time-offset,duration),sequenceTime:time};
    }
    offset += duration;
  }
}
export function trimPlacement(clips,id,start,end) {
  const clip=clips.find(item=>item.clip_id===id);
  if (!clip || !/^[0-9]{1,10}$/.test(String(start)) || !/^[0-9]{1,10}$/.test(String(end))) {
    throw new Error('Use whole frame numbers for the trim.');
  }
  const from=Number(start), to=Number(end);
  if (from>=to || to>clip.frames) throw new Error(`Use a start before the end, within frames 0–${clip.frames}.`);
  return placements(clips).map(item=>item.clip_id===id ? {...item,in_frame:from,out_frame:to} : item);
}
export function movePlacement(clips,id,direction) {
  const draft=placements(clips), index=draft.findIndex(clip=>clip.clip_id===id);
  if (index<0 || ![-1,1].includes(direction)) throw new Error('Choose a clip to move.');
  const next=index+direction;
  if (next>=0 && next<draft.length) [draft[index],draft[next]]=[draft[next],draft[index]];
  return draft;
}
export function formatTime(value) {
  const seconds=Math.max(0,Number.isFinite(value)?value:0);
  return `${Math.floor(seconds/60)}:${(seconds%60).toFixed(2).padStart(5,'0')}`;
}
export async function apiJSON(url,options={},fetcher=fetch) {
  if (!/^\/api\/timeline\/(?:projects|exports)(?:\/[a-f0-9]{32}(?:\/(?:clips|imports|export))?)?$/.test(url)) {
    throw new Error('Invalid sequence API route.');
  }
  let response;
  try { response=await fetcher(url,{credentials:'same-origin',...options,
    signal:options.signal || AbortSignal.timeout(options.method && options.method !== 'GET' ? 180000:20000)}); }
  catch { throw new Error('Connection interrupted. Reload the saved sequence before retrying a change.'); }
  let data;
  try { data=await response.json(); } catch { throw new Error('The studio returned an unreadable response. Reload to check its saved state.'); }
  if (!response.ok) {
    const message=typeof data?.detail==='string' ? data.detail : 'The sequence request could not be completed.';
    const error=new Error(message); error.status=response.status; throw error;
  }
  return data;
}

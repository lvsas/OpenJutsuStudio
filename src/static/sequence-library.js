/* Read-only discovery projection; never creates a Take, placement or native state. */
const validId=id=>typeof id==='string'&&/^[a-f0-9]{32}$/.test(id);
const engines=new Set(['minimax-h3','ltx25-ripple']);
export function nativeVersionsForSwap(entries, jobId) {
  if(!Array.isArray(entries)||!validId(jobId))return [];
  return entries.filter(entry=>validId(entry.take?.take_id)&&(entry.take.origin?.source_job===jobId
    ||Array.isArray(entry.project_job_ids)&&entry.project_job_ids.includes(jobId)));
}
export function mergeSequenceLibrary(nativeEntries,jobs) {
  if(!Array.isArray(nativeEntries)||!Array.isArray(jobs))throw new Error('The creation library response was invalid.');
  const entries=nativeEntries.map(entry=>({...entry,project_job_ids:[]}));
  const seen=new Set();
  for(const row of jobs) {
    if(!validId(row.job_id)||!engines.has(row.engine)||row.status!=='done'||seen.has(row.job_id))continue;
    seen.add(row.job_id);
    const matches=entries.filter(entry=>entry.take&&(entry.take.origin?.source_job===row.job_id
      ||(validId(row.native_take_id)&&entry.take.take_id===row.native_take_id)));
    if(matches.length) {
      for(const entry of matches)entry.project_job_ids.push(row.job_id);
      continue;
    }
    entries.push({kind:'swap',job:{job_id:row.job_id,engine:row.engine,status:'done',created:row.created},
      media_url:`/api/jobs/${row.job_id}/result`});
  }
  return entries;
}

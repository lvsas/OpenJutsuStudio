/* Library identity and display only. Video-only Swaps never acquire a Take family. */
export const isSwap=entry=>entry?.kind==='swap';
export const sourceKind=entry=>isSwap(entry)?'swap':'native';
export const sourceId=entry=>isSwap(entry)?entry.job.job_id:entry?.take?.take_id;
export const sourceKey=entry=>`${sourceKind(entry)}:${sourceId(entry)}`;
export function sourceDuration(entry) {
  // The Swap library contract contains no measured duration. Do not infer it
  // from an engine, creation date, generation preset or a neighbouring Take.
  if(!entry||isSwap(entry))return null;
  const context=entry.take?.family?.context;
  return Number.isFinite(context?.delivered_frames)&&context.delivered_frames>0
    &&Number.isFinite(context?.fps)&&context.fps>0?context.delivered_frames/context.fps:null;
}
export function sourceLabel(entry) {
  if(!entry)return 'Unavailable take';
  if(isSwap(entry))return entry.job.engine==='minimax-h3'?'H3 Swap':entry.job.engine==='ltx25-ripple'?'LTX Swap':'Swap';
  const record=entry.take;
  const kind=record.lineage.relation==='extends'?'Extension':record.lineage.parent_id?'Continuation':'Take';
  const duration=sourceDuration(entry);
  return duration===null?kind:`${kind} · ${duration.toFixed(1)} s`;
}

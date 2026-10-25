/* Intentional placements and drafts. No media, ancestry or network side effects. */
const ID = /^[a-f0-9]{32}$/;
const assertId = id => { if (!ID.test(id || '')) throw new Error('Invalid take or placement.'); };
export const defaultDraft = () => ({prompt:'',seed:'',raw_frames:277});
export const emptyWorkspace = () => ({project_id:null,title:'Untitled sequence',revision:0,
  placements:[],selected_placement_id:null,drafts:{}});
export function addPlacement(state, takeId, placementId, afterId = null, sourceKind = 'native') {
  assertId(takeId); assertId(placementId);
  if(!['native','swap'].includes(sourceKind))throw new Error('Invalid source kind.');
  if (state.placements.some(p=>p.placement_id===placementId)) throw new Error('Duplicate placement.');
  const placements=[...state.placements];
  const index=afterId ? placements.findIndex(p=>p.placement_id===afterId) : placements.length-1;
  if(afterId && index<0) throw new Error('The starting placement is no longer here.');
  placements.splice(index+1,0,{placement_id:placementId,take_id:takeId,...(sourceKind==='swap'?{source_kind:'swap'}:{})});
  return {...state,placements,selected_placement_id:placementId,
    drafts:{...state.drafts,[placementId]:defaultDraft()}};
}
export function removePlacement(state,id) {
  const index=state.placements.findIndex(p=>p.placement_id===id);
  const placements=state.placements.filter(p=>p.placement_id!==id);
  const drafts={...state.drafts}; delete drafts[id];
  const selected=state.selected_placement_id===id
    ? (placements[Math.max(0,index-1)]?.placement_id || null) : state.selected_placement_id;
  return {...state,placements,drafts,selected_placement_id:selected};
}
export function movePlacement(state,id,offset) {
  const placements=[...state.placements], index=placements.findIndex(p=>p.placement_id===id);
  const next=index+offset;
  if(index<0 || next<0 || next>=placements.length) return state;
  [placements[index],placements[next]]=[placements[next],placements[index]];
  return {...state,placements};
}
export function saveDraft(state,id,changes) {
  if(!state.placements.some(p=>p.placement_id===id)) throw new Error('This placement is no longer here.');
  return {...state,drafts:{...state.drafts,[id]:{...defaultDraft(),...state.drafts[id],...changes}}};
}
export function exactSeed(seed) {
  if(typeof seed!=='string' || !/^\d{1,20}$/.test(seed) || BigInt(seed)>18446744073709551615n)
    throw new Error('Use a whole-number seed between 0 and 18446744073709551615.');
  return BigInt(seed).toString();
}
export function randomSeed() {
  const words=new Uint32Array(2); crypto.getRandomValues(words);
  return ((BigInt(words[0])<<32n)|BigInt(words[1])).toString();
}
export function attemptBody({request_id,prompt,raw_frames,count=1,seed='',random=randomSeed}) {
  if(!Number.isInteger(count)||count<1||count>4)throw new Error('Choose between one and four candidates.');
  const seeds=[];
  if(seed) {
    const first=BigInt(exactSeed(seed));
    for(let i=0;i<count;i++)seeds.push(((first+BigInt(i))%(1n<<64n)).toString());
  } else {
    const unique=new Set();
    for(let tries=0;unique.size<count&&tries<128;tries++)unique.add(exactSeed(random()));
    if(unique.size!==count)throw new Error('Distinct seeds could not be prepared. Try again.');
    seeds.push(...unique);
  }
  // Reuse the existing strict direction/frame/ID validation, without parsing
  // either the single seed or the exact multi-seed JSON through Number().
  forwardBody({request_id,prompt,raw_frames,seed:seeds[0]});
  const fields=JSON.stringify({request_id,prompt,raw_frames});
  return fields.slice(0,-1)+',"seeds":['+seeds.join(',')+']}';
}
export function forwardBody({request_id,prompt,raw_frames,seed}) {
  assertId(request_id);
  if(typeof prompt!=='string' || !prompt.trim()) throw new Error('Describe what should happen.');
  if(!Number.isInteger(raw_frames) || raw_frames<5 || raw_frames>3600 || (raw_frames-5)%17)
    throw new Error('Choose a supported length.');
  // The existing API requires a JSON integer. Emit the validated decimal literal
  // directly: converting a 64-bit seed through Number irreversibly rounds it.
  const fields=JSON.stringify({request_id,prompt,raw_frames});
  return fields.slice(0,-1)+',"seed":'+exactSeed(seed)+'}';
}

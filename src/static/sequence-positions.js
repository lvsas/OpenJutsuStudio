/* Positions express intent; they never imply ancestry or start computation. */
import {addPlacement} from './sequence-state.js';
const ID=/^[a-f0-9]{32}$/;
export function positionsOf(state) {
  const placements=state.placements;
  return Array.from({length:placements.length+1},(_,index)=>{
    const left=placements[index-1]?.placement_id??null;
    const right=placements[index]?.placement_id??null;
    return {left,right,mode:!left&&!right?'root':!left?'prepend':!right?'forward':'bridge'};
  });
}
export function resolvePosition(state,position) {
  if(!position||![position.left,position.right].every(id=>id===null||typeof id==='string'&&ID.test(id)))
    throw new Error('Choose a current empty slot.');
  const found=positionsOf(state).find(p=>p.left===position.left&&p.right===position.right);
  if(!found)throw new Error('This position changed. Choose a current empty slot; your takes are untouched.');
  return {...found,mode:position.mode==='root'?'root':found.mode};
}
export function positionKey(position) {
  return `${position.mode}:${position.left??'start'}:${position.right??'end'}`;
}
export function positionFromKey(state,key) {
  if(typeof key!=='string'||!/^(root|forward|prepend|bridge):(start|[a-f0-9]{32}):(end|[a-f0-9]{32})$/.test(key))
    throw new Error('Choose a current empty slot.');
  const [mode,left,right]=key.split(':');
  const position=resolvePosition(state,{mode,left:left==='start'?null:left,right:right==='end'?null:right});
  if(position.mode!==mode)throw new Error('This position changed. Choose a current empty slot.');
  return position;
}
export function selectPosition(state,position,{mode=position.mode}={}) {
  const actual=resolvePosition(state,{left:position.left,right:position.right});
  if(mode!=='root'&&mode!==actual.mode)throw new Error('This operation does not match the chosen position.');
  const chosen={...actual,mode},key=positionKey(chosen),drafts=state.position_drafts??{};
  const draft=drafts[key]??{mode,prompt:'',seed:'',raw_frames:mode==='root'?124:277,reference_ids:[],reference_mode:mode==='root'?'custom':'inherit',width:1024,height:576,count:1};
  return {...state,selected_position:key,position_drafts:{...drafts,[key]:draft}};
}
export function savePositionDraft(state,changes) {
  const position=positionFromKey(state,state.selected_position);
  const key=positionKey(position),prior=state.position_drafts?.[key];
  if(!prior)throw new Error('Select an empty slot before editing.');
  return {...state,position_drafts:{...state.position_drafts,[key]:{...prior,...changes,mode:prior.mode}}};
}
export function insertAtPosition(state,takeId,placementId,position) {
  const gap=resolvePosition(state,position);
  const next=addPlacement(state,takeId,placementId,gap.left);
  // The legacy add action appends when no left anchor is supplied. An explicit
  // start slot inserts before the first placement without changing any draft.
  if(gap.left===null)next.placements=[next.placements.at(-1),...state.placements];
  return next;
}
export const positionLabel=position=>({root:'New take',prepend:'Create a beginning',bridge:'Bridge these takes',forward:'Continue the story'})[position.mode];

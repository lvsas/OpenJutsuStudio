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
  return found;
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

/* Production sequence UI over the existing revisioned Timeline project store. */
import {emptyWorkspace,addPlacement,removePlacement,movePlacement,saveDraft} from './sequence-state.js';
import {positionsOf,resolvePosition,insertAtPosition,positionLabel,positionFromKey,positionKey,selectPosition as selectPositionState,savePositionDraft as savePositionDraftState} from './sequence-positions.js';
const el=id=>document.getElementById(id);
const uuid=()=>crypto.randomUUID().replace(/-/g,'');
const rememberKey='opengenjutsu.sequence.project';
const stored=key=>{try{return localStorage.getItem(key);}catch{return null;}};
const remember=(key,value)=>{try{localStorage.setItem(key,value);}catch{/* Server remains authoritative. */}};
export function mountSequence({onSelect,onPreview,onCompose,onPosition=()=>{},onError}) {
  let insertionPosition=null;
  let state=emptyWorkspace(),entries=[],version=0,savedVersion=0,saving=null,timer=null,conflicted=false,previewedId=null;
  const entryFor=id=>entries.find(e=>e.take.take_id===id);
  const status=text=>{el('native-save-state').textContent=text;};
  const selected=()=>state.placements.find(p=>p.placement_id===state.selected_placement_id);
  async function api(path,options={}) {
    const response=await fetch('/api/timeline'+path,{credentials:'same-origin',cache:'no-store',...options});
    const data=await response.json().catch(()=>({}));
    if(!response.ok) {
      const error=new Error(typeof data.detail==='string'?data.detail:'The sequence could not be saved.');
      error.status=response.status;throw error;
    }
    return data;
  }
  function shadow() {
    remember('opengenjutsu.sequence.recovery',JSON.stringify(state));
  }
  function change(next,{select=false}={}) {
    state=next;version++;let resetPosition=false;
    if(insertionPosition) {
      try {resolvePosition(state,insertionPosition);}
      catch {insertionPosition=null;state={...state,selected_position:null};onPosition(null);resetPosition=true;}
    }
    shadow();render();status('Saving…');
    if(select||resetPosition) notifySelection();
    clearTimeout(timer);timer=setTimeout(()=>flush().catch(()=>{}),350);
  }
  async function flush() {
    clearTimeout(timer);
    if(saving) {await saving;if(version===savedVersion)return state;}
    if(conflicted)throw new Error('Reload the saved sequence before editing again. Your draft is kept in this browser.');
    if(version===savedVersion)return state;
    saving=(async()=>{
      try {
        if(!state.project_id) {
          const project=await api('/projects',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({title:state.title})});
          state={...state,project_id:project.project_id,revision:project.revision};
          remember(rememberKey,state.project_id);await projectList();
        }
        while(savedVersion<version) {
          const snapshot=structuredClone(state),sentVersion=version;
          const response=await api(`/projects/${state.project_id}/native-workspace`,{
            method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({
              revision:snapshot.revision,title:snapshot.title,placements:snapshot.placements,
              selected_placement_id:snapshot.selected_placement_id,drafts:snapshot.drafts,
              ...(snapshot.position_drafts?{selected_position:snapshot.selected_position??null,
                position_drafts:snapshot.position_drafts}:{})})});
          state={...state,revision:response.revision};savedVersion=sentVersion;
        }
        shadow();status('Saved');el('native-reload').hidden=true;
      } catch(error) {
        conflicted=error.status===409;shadow();status(conflicted?'Save conflict — local draft kept':'Not saved — draft kept here');
        el('native-reload').hidden=false;onError(error.message);throw error;
      } finally {saving=null;}
      return state;
    })();
    return saving;
  }
  function notifySelection() {
    const placement=selected();
    previewedId=placement?.take_id||null;markLibrarySelection();
    onSelect(placement?entryFor(placement.take_id):null,placement,
      placement?state.drafts[placement.placement_id]:null);
    if(state.selected_position) {
      insertionPosition=positionFromKey(state,state.selected_position);
      onPosition(structuredClone(insertionPosition),structuredClone(state.position_drafts[state.selected_position]));
    }
  }
  function select(id) {
    insertionPosition=null;onPosition(null);
    change({...state,selected_placement_id:id,selected_position:null},{select:true});
  }
  function showLibrary(open,{focus=false}={}) {
    el('native-library').hidden=!open;
    el('native-library-toggle').setAttribute('aria-expanded',String(open));
    if(focus)(open?el('native-search'):el('native-library-toggle')).focus();
  }
  function markLibrarySelection() {
    for(const row of el('native-takes').children)
      row.children[0]?.setAttribute('aria-pressed',String(row.dataset.takeId===previewedId));
  }
  function focusLibraryAdd(id) {
    [...el('native-takes').children].find(row=>row.dataset.takeId===id)?.children[1]?.focus({preventScroll:true});
  }
  function add(id,afterId=null,draft=null) {
    if(!entryFor(id))return;
    let next=insertionPosition&&!afterId
      ? insertAtPosition(state,id,uuid(),insertionPosition) : addPlacement(state,id,uuid(),afterId);
    insertionPosition=null;onPosition(null);
    if(draft)next=saveDraft(next,next.selected_placement_id,draft);
    change({...next,selected_position:null},{select:true});
  }
  function poster(entry) {
    const image=document.createElement('img');image.alt='';image.loading='lazy';
    image.className='sequence-poster';image.src=`/api/continuity/takes/${entry.take.take_id}/poster`;
    image.addEventListener('error',()=>{image.hidden=true;image.parentElement?.classList.add('poster-unavailable');});
    return image;
  }
  function label(entry) {
    return `${entry.take.lineage.parent_id?'Continuation':'Take'} · ${entry.take.take_id.slice(0,8)}`;
  }
  function duration(entry) {
    const c=entry.take.family.context;return `${(c.delivered_frames/c.fps).toFixed(1)} s`;
  }
  function action(text,fn,className='btn btn-ghost') {
    const button=document.createElement('button');button.type='button';button.className=className;
    button.textContent=text;button.addEventListener('click',fn);return button;
  }
  function drawLibrary() {
    const container=el('native-takes'),search=el('native-search').value.toLowerCase();container.replaceChildren();
    const filtered=entries.filter(e=>label(e).toLowerCase().includes(search));
    el('pool-count').textContent=`${filtered.length} of ${entries.length} takes`;
    for(const entry of filtered.slice(0,100)) {
      const id=entry.take.take_id,row=document.createElement('li');row.className='library-take';
      const preview=action('',()=>{previewedId=id;markLibrarySelection();onPreview(entry);},'library-preview');
      preview.setAttribute('aria-pressed',String(id===previewedId));
      preview.setAttribute('aria-label',`Preview ${label(entry)}`);preview.append(poster(entry));
      const text=document.createElement('span');text.className='library-take-info';
      const name=document.createElement('strong');name.textContent=label(entry);
      const info=document.createElement('small');info.textContent=`H3 · ${duration(entry)}${state.placements.some(p=>p.take_id===id)?' · In this sequence':''}`;
      text.append(name,info);preview.append(text);
      const append=action('+',()=>{add(id);focusLibraryAdd(id);},'btn btn-secondary library-add');append.setAttribute('aria-label',`Add ${label(entry)} to sequence`);
      row.draggable=true;row.dataset.takeId=id;
      row.addEventListener('dragstart',event=>{event.dataTransfer.setData('text/plain',id);event.dataTransfer.effectAllowed='copy';});
      row.append(preview,append);container.append(row);
    }
    if(!filtered.length) {const text=document.createElement('li');text.className='microcopy';text.textContent=entries.length?'No matching takes.':'No saved native takes yet. Create a Swap in H3 Studio to get started.';container.append(text);}
  }
  function openPosition(position,options={}) {
    const next=selectPositionState(state,position,options);
    insertionPosition=positionFromKey(next,next.selected_position);
    change(next);
    onPosition(structuredClone(insertionPosition),structuredClone(state.position_drafts[state.selected_position]),{focus:true});
  }
  function positionSlot(position) {
    const slot=document.createElement('li');slot.className='sequence-gap position-slot';
    slot.dataset.mode=position.mode;
    const open=action('',()=>{
      openPosition(position);
    },'position-create');
    open.setAttribute('aria-label',positionLabel(position));
    open.setAttribute('aria-controls','position-context');
    open.setAttribute('aria-pressed',String(insertionPosition?.left===position.left&&insertionPosition?.right===position.right));
    const mark=document.createElement('span');mark.className='position-mark';mark.textContent='+';mark.setAttribute('aria-hidden','true');
    const name=document.createElement('strong');name.textContent=positionLabel(position);
    const hint=document.createElement('small');hint.textContent='or drop a saved take';
    open.append(mark,name,hint);slot.append(open);
    slot.addEventListener('dragover',event=>{event.preventDefault();slot.classList.add('is-target');});
    slot.addEventListener('dragleave',()=>slot.classList.remove('is-target'));
    slot.addEventListener('drop',event=>{
      event.preventDefault();event.stopPropagation?.();slot.classList.remove('is-target');el('take-board').classList.remove('is-target');
      try {
        const id=event.dataTransfer.getData('text/plain');
        if(!entryFor(id))throw new Error('Drop a saved take from Your takes.');
        insertionPosition=resolvePosition(state,position);add(id);
      }
      catch(error){onError(error.message);}
    });
    return slot;
  }
  function drawRail() {
    const rail=el('board-track');rail.replaceChildren();
    el('native-rail-empty').hidden=state.placements.length>0;
    el('board-hint').textContent=state.placements.length?`${state.placements.length} chosen takes · order is yours`:'Nothing is added automatically';
    const positions=positionsOf(state);
    rail.append(positionSlot(positions[0]));
    state.placements.forEach((placement,index)=>{
      const entry=entryFor(placement.take_id),slot=document.createElement('li');slot.className='sequence-slot';
      slot.dataset.placementId=placement.placement_id;
      const card=action('',()=>select(placement.placement_id),'sequence-take');
      card.setAttribute('aria-pressed',String(placement.placement_id===state.selected_placement_id));
      const name=document.createElement('strong');name.textContent=entry?label(entry):`Unavailable · ${placement.take_id.slice(0,8)}`;
      if(entry)card.append(poster(entry));
      const time=document.createElement('small');time.textContent=entry?duration(entry):'Source not listed';
      card.append(name,time);
      const tools=document.createElement('div');tools.className='sequence-take-tools';
      const previous=action('←',()=>change(movePlacement(state,placement.placement_id,-1)));
      previous.disabled=index===0;previous.setAttribute('aria-label','Move take earlier');
      const next=action('→',()=>change(movePlacement(state,placement.placement_id,1)));
      next.disabled=index===state.placements.length-1;next.setAttribute('aria-label','Move take later');
      const remove=action('Remove',()=>change(removePlacement(state,placement.placement_id),{select:true}));
      remove.setAttribute('aria-label',`Remove ${entry?label(entry):'take'} from sequence only`);
      tools.append(previous,next,remove);slot.append(card,tools);rail.append(slot);
      rail.append(positionSlot(positions[index+1]));
    });
  }
  function render() {
    drawLibrary();drawRail();
    if(document.activeElement!==el('native-project-title'))el('native-project-title').value=state.title;
    el('native-project-picker').value=state.project_id||'';
  }
  async function projectList() {
    const {projects}=await api('/projects'),picker=el('native-project-picker');
    picker.replaceChildren(new Option('New unsaved sequence',''));
    for(const p of projects)picker.append(new Option(p.title,p.project_id));
    picker.value=state.project_id||'';
  }
  async function load(id) {
    state=await api(`/projects/${id}/native-workspace`);version=0;savedVersion=0;conflicted=false;insertionPosition=state.selected_position?positionFromKey(state,state.selected_position):null;onPosition(null);
    remember(rememberKey,id);status('Saved');el('native-reload').hidden=true;render();notifySelection();
  }
  el('native-library-toggle').addEventListener('click',()=>{
    showLibrary(el('native-library').hidden,{focus:true});
  });
  el('native-rail-add').addEventListener('click',()=>showLibrary(true,{focus:true}));
  el('native-library-close').addEventListener('click',()=>showLibrary(false,{focus:true}));
  el('native-library').addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();showLibrary(false,{focus:true});}
  });
  el('native-search').addEventListener('input',drawLibrary);
  el('native-project-title').addEventListener('input',()=>{
    const title=el('native-project-title').value.trim();if(title)change({...state,title});
  });
  el('native-new-sequence').addEventListener('click',async()=>{
    try {await flush();state=emptyWorkspace();version=0;savedVersion=0;conflicted=false;
      insertionPosition=null;onPosition(null);
      remember(rememberKey,'');render();notifySelection();status('Not started');
      showLibrary(true);}
    catch(error){onError(error.message);}
  });
  el('native-project-picker').addEventListener('change',async event=>{
    const id=event.target.value;if(!id){event.target.value=state.project_id||'';return;}
    try{await flush();await load(id);}catch(error){onError(error.message);event.target.value=state.project_id||'';}
  });
  el('native-reload').addEventListener('click',()=>{
    if(state.project_id)load(state.project_id).catch(error=>onError(error.message));
  });
  el('take-board').addEventListener('dragover',event=>{
    event.preventDefault();event.dataTransfer.dropEffect='copy';el('take-board').classList.add('is-target');
  });
  el('take-board').addEventListener('dragleave',()=>el('take-board').classList.remove('is-target'));
  el('take-board').addEventListener('drop',event=>{
    event.preventDefault();el('take-board').classList.remove('is-target');add(event.dataTransfer.getData('text/plain'));
  });
  el('board-track').addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight'].includes(event.key)||event.target.tagName==='INPUT')return;
    const i=state.placements.findIndex(p=>p.placement_id===state.selected_placement_id);
    const next=state.placements[i+(event.key==='ArrowRight'?1:-1)];
    if(next){event.preventDefault();select(next.placement_id);}
  });
  window.addEventListener('beforeunload',event=>{
    if(version!==savedVersion){event.preventDefault();event.returnValue='';}
  });
  return {
    async init(items) {
      entries=items;await projectList();const id=stored(rememberKey);
      if(id && /^[a-f0-9]{32}$/.test(id)) {try{await load(id);}catch(error){onError(error.message);render();}}
      else {render();notifySelection();status('Not started');}
      showLibrary(true);
    },
    refresh(items){entries=items;render();},
    state:()=>structuredClone(state), selected,
    clearPosition(){insertionPosition=null;onPosition(null);change({...state,selected_position:null},{select:true});},
    openPosition,
    positionDraft(){return state.position_drafts?.[state.selected_position]??null;},
    setPositionDraft(changes){change(savePositionDraftState(state,changes));},
    addAtPosition(){showLibrary(true,{focus:true});},
    composePosition(){
      const gap=resolvePosition(state,insertionPosition);
      if(gap.mode!=='forward')throw new Error('This native operation is not available in the composer yet.');
      select(gap.left);onCompose(entryFor(selected().take_id),selected());
    },
    draft(){const p=selected();return p?state.drafts[p.placement_id]:null;},
    setDraft(changes){const p=selected();if(p)change(saveDraft(state,p.placement_id,changes));},
    flush,
    place(takeId,draft){add(takeId,null,draft);},
    async insertResult(takeId,projectId,afterId,position=null) {
      if(!entryFor(takeId)||state.project_id!==projectId)return false;
      if(position) {
        const next=insertAtPosition(state,takeId,uuid(),position);
        insertionPosition=null;onPosition(null);
        change({...next,selected_position:null},{select:true});
      } else {
        if(!state.placements.some(p=>p.placement_id===afterId))return false;
        add(takeId,afterId);
      }
      await flush();return 'Saved with continuation state.';
    },
    compose(){const p=selected();if(p)onCompose(entryFor(p.take_id),p);}
  };
}

/* One production composer for parentless and position-anchored native takes. */
import {attemptBody} from './sequence-state.js';
import {positionLabel,resolvePosition} from './sequence-positions.js';
const uuid=()=>crypto.randomUUID().replace(/-/g,'');
export function mountPositionGeneration({sequence,getJSON,byId,duration,onUpdate,onMessage}) {
  let position=null,draft=null,available=false,inherited=[],token=0,busy=false,referenceLimit=null,referenceError=false;
  const custom=()=>position?.mode==='root'||draft?.reference_mode==='custom';
  const referenceCount=()=>custom()?(draft?.reference_ids?.length||0):inherited.length;
  const save=changes=>{sequence.setPositionDraft(changes);draft=sequence.positionDraft();};
  const fields=()=>({prompt:byId('forward-prompt').value,seed:byId('forward-seed').value.trim(),
    raw_frames:Number(byId('forward-length').value),count:Number(byId('forward-variants').value)||1});
  async function upload(file) {
    const body=new FormData();body.append('image',file);
    const response=await fetch('/api/continuity/root-references',{method:'POST',credentials:'same-origin',body});
    const result=await response.json().catch(()=>({}));
    if(!response.ok||!/^[a-f0-9]{32}$/.test(result.reference_id||''))
      throw new Error(typeof result.detail==='string'?result.detail:'The reference could not be saved.');
    return result.reference_id;
  }
  async function inheritedIds(skip=-1) {
    const ids=[];
    for(let i=0;i<inherited.length;i++) {
      if(i===skip)continue;
      const response=await fetch(inherited[i],{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw new Error('The inherited reference could not be read.');
      const blob=await response.blob();ids.push(await upload(new File([blob],'reference',{type:blob.type})));
    }
    return ids;
  }
  async function editReferences(transform) {
    if(busy||!position)return;
    const current=token;busy=true;onUpdate();
    try {
      const ids=await transform();
      if(current!==token)return;
      save({reference_ids:ids,reference_mode:'custom'});referenceError=false;renderReferences();
      onMessage('References saved for this position only. Original takes are unchanged.');
    } catch(error){if(current===token)onMessage(error.message);}
    finally{if(current===token){busy=false;onUpdate();}}
  }
  function renderReferences() {
    const list=byId('forward-reference-list');list.replaceChildren();
    byId('forward-references').hidden=false;
    const urls=custom()?(draft.reference_ids||[]).map(id=>`/api/continuity/root-references/${id}`):inherited;
    byId('forward-reference-count').textContent=` · ${urls.length}${custom()?'':' inherited'}`;
    if(referenceError)byId('native-readiness').textContent='References could not be loaded. Reopen this position to retry; timing and your draft are kept. No generation will start.';
    else if(available)byId('native-readiness').textContent=referenceLimit!==null&&urls.length>referenceLimit
      ?`This target accepts up to ${referenceLimit} references. Remove a reference to continue.`
      :urls.length?'Saved timing checked.':'Add a reference to start.';
    if(!urls.length) {
      const hint=document.createElement('span');hint.className='microcopy';
      hint.textContent='Add at least one reference image. It stays attached to the generated take.';list.append(hint);
    }
    urls.forEach((url,index)=>{
      const slot=document.createElement('span');slot.className='forward-reference-slot';
      const image=document.createElement('img');image.src=url;image.alt=`Reference ${index+1}`;
      image.width=56;image.height=56;image.className='forward-reference';
      const remove=document.createElement('button');remove.type='button';remove.className='btn btn-ghost reference-order';
      remove.textContent='Remove';remove.setAttribute('aria-label',`Remove reference ${index+1} from this draft`);
      remove.addEventListener('click',()=>editReferences(async()=>custom()
        ?draft.reference_ids.filter((_,i)=>i!==index):inheritedIds(index)));
      slot.append(image,remove);list.append(slot);
    });
  }
  function close(){++token;position=null;draft=null;available=false;busy=false;inherited=[];byId('root-settings').hidden=true;}
  async function open(next,saved) {
    const current=++token;position=next;draft=structuredClone(saved);available=false;busy=false;inherited=[];referenceLimit=null;referenceError=false;
    byId('forward-form').hidden=false;
    byId('forward-prompt').value=draft.prompt;byId('forward-seed').value=draft.seed;
    byId('forward-variants').value=String(draft.count??1);duration.reset(draft.raw_frames);
    byId('native-title').textContent=positionLabel(position);
    byId('root-settings').hidden=position.mode!=='root';
    const size=byId('root-size'),value=`${draft.width}x${draft.height}`;
    size.replaceChildren(...[['1024x576','Landscape'],['576x1024','Portrait'],['768x768','Square']]
      .map(([v,text])=>new Option(`${text} · ${v.replace('x',' × ')}`,v)));
    if(!['1024x576','576x1024','768x768'].includes(value))size.append(new Option(`Saved · ${value.replace('x',' × ')}`,value));
    size.value=value;
    const state=sequence.state(),left=state.placements.find(p=>p.placement_id===position.left),
      right=state.placements.find(p=>p.placement_id===position.right);
    const query=new URLSearchParams({mode:position.mode});
    if(position.mode!=='root')query.set('take_id',(position.mode==='prepend'?right:left).take_id);
    if(position.mode==='bridge')query.set('second_take_id',right.take_id);
    renderReferences();onUpdate();
    try {
      const ready=await getJSON('/api/continuity/composer-readiness?'+query);
      if(current!==token)return;
      available=ready.available===true;
      referenceLimit=Number.isInteger(ready.reference_limit)?ready.reference_limit:null;
      duration.ready(ready);
      byId('native-readiness').textContent=ready.reason||'Saved timing checked.';
      if(position.mode!=='root'&&!custom()) {
        const id=position.mode==='prepend'?right.take_id:left.take_id;
        try {
          const refs=await getJSON(`/api/continuity/takes/${id}/references`);
          if(current!==token)return;
          inherited=refs.references.map(r=>`/api/continuity/takes/${id}/references/${r.index}`);
          renderReferences();
        } catch(error){if(current===token)referenceError=true;}
      }
    } catch(error){if(current===token){available=false;duration.unavailable();byId('native-readiness').textContent='Timing check request failed. Reopen this position to retry; your draft is kept.';}}
    finally{if(current===token){renderReferences();onUpdate();}}
  }
  byId('root-size').addEventListener('change',()=>{
    if(!position||position.mode!=='root')return;
    const [width,height]=byId('root-size').value.split('x').map(Number);save({width,height});
  });
  return {open,close,active:()=>!!position,
    valid:()=>!!position&&available&&!referenceError&&!busy&&referenceCount()>0
      &&(referenceLimit===null||referenceCount()<=referenceLimit)&&duration.valid(),
    saveFields(){if(position)save(fields());},
    add:file=>editReferences(async()=>[...(custom()?draft.reference_ids:await inheritedIds()),await upload(file)]),
    async useCharacter(){
      const image=byId('native-character-image');
      if(!image.getAttribute('src'))return;
      const response=await fetch(image.src,{credentials:'same-origin'});
      if(!response.ok){onMessage('The character reference could not be read.');return;}
      const blob=await response.blob();return this.add(new File([blob],'character',{type:blob.type}));
    },
    request(request_id=uuid()) {
      const state=sequence.state(),gap=resolvePosition(state,position);save(fields());
      const left=state.placements.find(p=>p.placement_id===gap.left),right=state.placements.find(p=>p.placement_id===gap.right);
      let body=attemptBody({...fields(),request_id}),extra;
      if(gap.mode==='root')extra={reference_ids:draft.reference_ids,width:draft.width,height:draft.height};
      else extra={mode:gap.mode,...(gap.mode==='bridge'?{second_take_id:right.take_id}:{}),
        ...(custom()?{reference_ids:draft.reference_ids}:{})};
      body=body.slice(0,-1)+','+JSON.stringify(extra).slice(1);
      return {request_id,take_id:gap.mode==='root'?null:(gap.mode==='prepend'?right:left).take_id,
        mode:gap.mode,second_take_id:gap.mode==='bridge'?right.take_id:null,
        after:gap.left,position:gap,project_id:state.project_id,body};
    },
  };
}

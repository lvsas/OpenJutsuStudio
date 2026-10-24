/* Browser recovery over the existing durable attempts API. GET never creates work. */
export const PENDING_KEY='opengenjutsu.sequence.pending-generation';
const id=value=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value);
const terminal=value=>value==='done'||value==='failed';
const mode=value=>value.mode||'forward';
const validPosition=value=>value&&['root','forward','prepend','bridge'].includes(value.mode)&&[value.left,value.right].every(v=>v===null||id(v));
const validSource=value=>mode(value)==='root'?value.take_id===null:id(value.take_id);
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
export function createAttemptClient({fetcher=fetch,storage=localStorage,onState=()=>{},
  onView=()=>{},onMessage=()=>{},sleep=pause,interval=4000}={}) {
  let receipt=null,invalid=false,token=0,phase='idle',legacy=[],canDismiss=false;
  try {const raw=storage.getItem(PENDING_KEY);if(raw)receipt=JSON.parse(raw);}
  catch {invalid=true;}
  if(receipt&&(!validSource(receipt)||(receipt.project_id!=null&&!id(receipt.project_id))
      ||(receipt.after!=null&&!id(receipt.after))))invalid=true;
  const blocked=()=>invalid||!!receipt&&!terminal(receipt.status);
  const emit=(next,extra={})=>{
    phase=next;onState({phase,blocked:blocked(),receipt,canDismiss,attempts:legacy,...extra});
  };
  function save(next) {
    // Refuse submission if browser recovery cannot be saved first. The server
    // remains authoritative; after a lost reply its request_id can be looked up.
    storage.setItem(PENDING_KEY,JSON.stringify(next));receipt=next;
  }
  async function get(url) {
    const response=await fetcher(url,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(20000)});
    if(!response.ok){const error=new Error('The saved attempt could not be read.');error.status=response.status;throw error;}
    return response.json();
  }
  function validView(view) {
    if(!view||!id(view.attempt_id)||view.take_id!==receipt.take_id||mode(view)!==mode(receipt)
        ||(mode(receipt)==='bridge'&&view.second_take_id!==receipt.second_take_id)||!Array.isArray(view.candidates)
        ||!['pending','running','done','failed'].includes(view.status))
      throw new Error('The saved attempt response was invalid.');
    return view;
  }
  async function follow(initial,current) {
    let view=validView(initial);
    while(current===token) {
      save({...receipt,version:2,attempt_id:view.attempt_id,status:view.status});
      canDismiss=terminal(view.status);await onView(view,receipt);
      if(current!==token)return;
      emit(canDismiss?'terminal':'running');
      if(canDismiss)return view;
      await sleep(interval);
      if(current!==token)return;
      view=validView(await get(`/api/continuity/attempts/${receipt.attempt_id}`));
    }
  }
  function disconnected(error) {
    canDismiss=false;emit('disconnected');
    onMessage(error?.message||'Connection lost. The saved attempt is not resubmitted.');
  }
  async function send() {
    const current=++token;emit('sending');
    try {
      const response=await fetcher(mode(receipt)==='root'?'/api/continuity/roots/attempts':`/api/continuity/takes/${receipt.take_id}/attempts`,{
        method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{'Content-Type':'application/json'},body:receipt.body,signal:AbortSignal.timeout(30000)});
      if(!response.ok) {
        const detail=await response.json().catch(()=>({}));
        if(response.status===400||response.status===422) {
          storage.removeItem(PENDING_KEY);receipt=null;canDismiss=false;emit('idle');
          onMessage(detail.detail||'The request was refused. Your draft stays unchanged.');return;
        }
        throw new Error(typeof detail.detail==='string'?detail.detail:'The request outcome could not be confirmed.');
      }
      if(current!==token)return;
      // Persist the server identity before polling or touching the candidate UI.
      return await follow(await response.json(),current);
    } catch(error){if(current===token)disconnected(error);}
  }
  async function recover() {
    if(invalid){emit('invalid');onMessage('This browser recovery note is invalid. No request has been sent.');return;}
    if(!receipt){emit('idle');return;}
    const current=++token;emit('checking');
    try {
      if(!id(receipt.attempt_id)&&!id(receipt.request_id)) {
        const result=await get(`/api/continuity/takes/${receipt.take_id}/attempts`);
        if(current!==token)return;
        legacy=Array.isArray(result.attempts)?result.attempts:[];
        canDismiss=!result.has_more&&legacy.every(v=>terminal(v.status));
        emit('legacy');onMessage('Choose a saved attempt to inspect. No generation has been restarted.');return;
      }
      const url=id(receipt.attempt_id)?`/api/continuity/attempts/${receipt.attempt_id}`
        :mode(receipt)==='root'?`/api/continuity/roots/attempts/by-request/${receipt.request_id}`
        :`/api/continuity/takes/${receipt.take_id}/attempts/by-request/${receipt.request_id}`;
      const view=await get(url);if(current===token)return await follow(view,current);
    } catch(error) {
      if(current!==token)return;
      if(error.status===404&&!id(receipt.attempt_id)&&receipt.body) {
        emit('not-found');onMessage('No saved request was found. Retry only with this same request identity.');
      } else disconnected(error);
    }
  }
  return {
    async submit(value) {
      if(blocked())throw new Error('Reconnect the previous attempt before generating again.');
      if(!id(value.request_id)||!validSource(value)||!id(value.project_id)
          ||!(validPosition(value.position)||id(value.after))||typeof value.body!=='string')throw new Error('Save a valid sequence and draft before generating.');
      // Keep the literal body: JSON.parse/stringify would round uint64 seeds.
      save({...value,version:2,attempt_id:null,status:'unknown'});canDismiss=false;
      return send();
    },
    recover,
    async retrySubmission() {
      if(phase!=='not-found'||!receipt?.body||!id(receipt.request_id))
        throw new Error('Reconnect this attempt without resubmitting it.');
      return send();
    },
    async selectLegacy(attemptId) {
      const found=legacy.find(v=>v.attempt_id===attemptId);
      if(!found||!id(attemptId))throw new Error('Choose an existing saved attempt.');
      save({...receipt,version:2,attempt_id:attemptId,status:found.status,mode:mode(found),second_take_id:found.second_take_id??null});
      return recover();
    },
    dismiss() {
      if(!canDismiss&&!terminal(receipt?.status))throw new Error('The attempt is not confirmed finished.');
      ++token;storage.removeItem(PENDING_KEY);receipt=null;legacy=[];canDismiss=false;emit('idle');
    },
    dispose(){++token;},
    blocked,
  };
}

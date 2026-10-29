import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createAttemptClient, PENDING_KEY} from '../src/static/continuity-attempt-client.js';
import {attemptBody} from '../src/static/sequence-state.js';
const TAKE='a'.repeat(32), REQUEST='b'.repeat(32), ATTEMPT='c'.repeat(32);
const anchor={take_id:TAKE,project_id:'d'.repeat(32),after:'e'.repeat(32)};
const view=status=>({attempt_id:ATTEMPT,take_id:TAKE,status,error:null,candidates:[]});
const body=()=>attemptBody({request_id:REQUEST,prompt:'Keep moving',raw_frames:158,count:2,seed:'18446744073709551615'});
const response=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>data});
function storage(initial=null){let raw=initial;return {getItem:()=>raw,setItem:(k,v)=>{raw=v;},removeItem:()=>{raw=null;},value:()=>raw};}
function harness({initial=null,fetcher}={}){
 const store=storage(initial),calls=[],states=[],views=[],messages=[];
 const client=createAttemptClient({storage:store,fetcher:async(url,opts={})=>{
  calls.push({url,method:opts.method||'GET',body:opts.body,receipt:store.value()});
  return fetcher(url,opts,calls.length);
 },onState:s=>states.push(s),onView:(v,r)=>views.push([v,r]),onMessage:m=>messages.push(m),sleep:async()=>{}});
 return {client,store,calls,states,views,messages};
}
test('explicit candidate count preserves exact seeds including uint64 wrap',()=>{
 const raw=body();assert.match(raw,/"seeds":\[18446744073709551615,0\]/);
 assert.equal(JSON.parse(raw).seeds.length,2);
 assert.throws(()=>attemptBody({request_id:REQUEST,prompt:'x',raw_frames:158,count:5,seed:'1'}));
});
test('receipt precedes POST and returned attempt id precedes first poll',async()=>{
 const h=harness({fetcher:async(url,opts)=>opts.method==='POST'?response(view('running'),202):response(view('done'))});
 await h.client.submit({...anchor,request_id:REQUEST,body:body()});
 assert.equal(h.calls[0].method,'POST');
 assert.equal(JSON.parse(h.calls[0].receipt).request_id,REQUEST);
 assert.equal(JSON.parse(h.calls[1].receipt).attempt_id,ATTEMPT);
 assert.equal(h.states.at(-1).blocked,false);
 assert.equal(JSON.parse(h.store.value()).status,'done','Keep remains recoverable after reload');
});
test('reload of known attempt uses only GET and returns original anchor',async()=>{
 const receipt={...anchor,request_id:REQUEST,attempt_id:ATTEMPT,body:body(),status:'running',version:2};
 const h=harness({initial:JSON.stringify(receipt),fetcher:async()=>response(view('done'))});
 await h.client.recover();assert.deepEqual(h.calls.map(c=>c.method),['GET']);
 assert.equal(h.views[0][1].after,anchor.after);assert.equal(h.states.at(-1).blocked,false);
});
test('lost POST reply recovers by request id without a second POST',async()=>{
 const first=harness({fetcher:async()=>{throw new Error('lost reply');}});
 await first.client.submit({...anchor,request_id:REQUEST,body:body()});
 assert.equal(first.states.at(-1).blocked,true);
 const second=harness({initial:first.store.value(),fetcher:async()=>response(view('done'))});
 await second.client.recover();assert.equal(second.calls[0].method,'GET');
 assert.match(second.calls[0].url,new RegExp(`/attempts/by-request/${REQUEST}$`));
 assert.equal(second.states.at(-1).blocked,false);
});
test('missing request never auto-posts; explicit retry keeps exact body and id',async()=>{
 const receipt={...anchor,request_id:REQUEST,attempt_id:null,body:body(),status:'unknown',version:2};
 let found=false;
 const h=harness({initial:JSON.stringify(receipt),fetcher:async(url,opts)=>{
  if(opts.method==='POST'){found=true;return response(view('done'),202);}
  return response({},404);
 }});
 await h.client.recover();assert.equal(found,false);assert.equal(h.states.at(-1).phase,'not-found');
 await h.client.retrySubmission();assert.equal(h.calls.at(-1).body,receipt.body);
 assert.equal(h.states.at(-1).blocked,false);
});
test('a failed poll keeps receipt and blocks duplicate submission',async()=>{
 let count=0;const h=harness({fetcher:async()=>{if(count++===0)return response(view('running'),202);throw Error('offline');}});
 await h.client.submit({...anchor,request_id:REQUEST,body:body()});
 assert.equal(h.states.at(-1).blocked,true);assert.equal(JSON.parse(h.store.value()).attempt_id,ATTEMPT);
 await assert.rejects(()=>h.client.submit({...anchor,request_id:REQUEST,body:body()}));
 assert.equal(h.calls.filter(c=>c.method==='POST').length,1);
});
test('legacy note lists saved attempts without starting or picking one automatically',async()=>{
 const h=harness({initial:JSON.stringify(anchor),fetcher:async()=>response({attempts:[view('failed')],has_more:false,total:1})});
 await h.client.recover();assert.equal(h.calls[0].method,'GET');assert.equal(h.views.length,0);
 assert.equal(h.states.at(-1).phase,'legacy');assert.equal(h.states.at(-1).canDismiss,true);
 h.client.dismiss();assert.equal(h.store.value(),null);
});
test('storage failure refuses new submission before network activity',async()=>{
 const store={getItem:()=>null,setItem:()=>{throw Error('quota');},removeItem:()=>{}};
 let calls=0;const c=createAttemptClient({storage:store,fetcher:async()=>{calls++;},onState:()=>{},onView:()=>{},onMessage:()=>{}});
 await assert.rejects(()=>c.submit({...anchor,request_id:REQUEST,body:body()}));assert.equal(calls,0);
});
test('confirmed precheck refusal releases receipt and permits a corrected draft',async()=>{
 for(const status of [400,422]) {
  const h=harness({fetcher:async()=>response({detail:'The saved anchor could not be read. No generation was created.'},status)});
  await h.client.submit({...anchor,request_id:REQUEST,body:body()});
  assert.equal(h.store.value(),null);assert.equal(h.client.blocked(),false);
  assert.equal(h.states.at(-1).phase,'idle');assert.equal(h.states.at(-1).canDismiss,false);
  assert.match(h.messages.at(-1),/No generation was created/);
  await assert.rejects(()=>h.client.retrySubmission(),/without resubmitting/);
  await h.client.submit({...anchor,request_id:'f'.repeat(32),body:body()});
  assert.equal(h.calls.length,2,'a corrected explicit submission is no longer blocked');
 }
});
test('generic 500 and recovery 404 cannot dismiss unknown work; exact retry can confirm refusal',async()=>{
 for(const postStatus of [500,404]) {
  let refused=false;
  const h=harness({fetcher:async(url,opts)=>opts.method==='POST'
   ?response({detail:refused?'No generation was created.':'Unknown outcome'},refused?422:postStatus)
   :response({},404)});
  await h.client.submit({...anchor,request_id:REQUEST,body:body()});
  const original=h.store.value();assert.ok(original);assert.equal(h.client.blocked(),true);
  assert.throws(()=>h.client.dismiss(),/not confirmed finished/);
  await h.client.recover();assert.equal(h.states.at(-1).phase,'not-found');
  assert.equal(h.states.at(-1).canDismiss,false);assert.equal(h.store.value(),original);
  assert.throws(()=>h.client.dismiss(),/not confirmed finished/);
  assert.deepEqual(h.calls.map(c=>c.method),['POST','GET'],'404 never automatically retries');
  refused=true;await h.client.retrySubmission();
  assert.equal(h.calls.at(-1).body,body(),'explicit retry preserves literal uint64 body and request id');
  assert.equal(h.store.value(),null);assert.equal(h.client.blocked(),false);
  assert.equal(h.states.at(-1).phase,'idle');
 }
});
test('invalid browser JSON is visible and never causes automatic POST',async()=>{
 const h=harness({initial:'{broken',fetcher:async()=>{throw Error('must not fetch');}});
 await h.client.recover();assert.equal(h.states.at(-1).phase,'invalid');assert.equal(h.calls.length,0);
});

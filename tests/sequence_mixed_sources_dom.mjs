/* Real-browser DOM harness; API fixtures do not prove backend writes or media decoding. */
import {mountSequence} from '../src/static/sequence-workspace.js';
const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32),D='d'.repeat(32);
const native=id=>({take:{take_id:id,family:{context:{delivered_frames:120,fps:24}},lineage:{relation:'root',parent_id:null}},media_url:`/native/${id}`});
const swap=(id,engine='minimax-h3')=>({kind:'swap',job:{job_id:id,engine,status:'done',created:'2026-01-01'},media_url:`/api/jobs/${id}/result`});
const assert=(condition,message)=>{if(!condition)throw Error(message);};
const equal=(actual,expected,message)=>assert(JSON.stringify(actual)===JSON.stringify(expected),`${message}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
const fixture=`<button id="native-rail-add">Add</button><button id="native-library-close">Close</button>
<section id="native-library"><input id="native-search"><select id="native-library-scope"><option value="project">Project</option><option value="common">Common</option></select><ul id="native-takes"></ul></section>
<span id="native-save-state"></span><button id="native-reload">Reload</button><span id="pool-count"></span>
<section id="take-board"><span id="native-rail-empty"></span><span id="board-hint"></span><ul id="board-track"></ul></section>`;
const el=id=>document.getElementById(id);
function drag(target,type,data){
  const dataTransfer=new DataTransfer();for(const [key,value] of Object.entries(data))dataTransfer.setData(key,value);
  target.dispatchEvent(new DragEvent(type,{bubbles:true,cancelable:true,dataTransfer}));return dataTransfer;
}
export async function runMixedSequenceDOMTests(){
  let saved={project_id:C,title:'Mixed project',revision:1,placements:[],selected_placement_id:null,drafts:{}};
  const calls=[],errors=[],previews=[],selections=[],passed=[];
  const entries=[native(A),swap(A),swap(B,'ltx25-ripple'),native(D)];entries[3].project_job_ids=[B];
  const originalFetch=window.fetch;
  window.fetch=async(url,options={})=>{
    calls.push({url,options});
    if(url.endsWith('/assets'))return Response.json({project_id:C,assets:{takes:[A],jobs:[B]}});
    if(url.endsWith('/native-workspace')){
      if(options.method==='PATCH'){saved={...saved,...JSON.parse(options.body),revision:saved.revision+1};}
      return Response.json(structuredClone(saved));
    }
    throw Error(`Unexpected request ${url}`);
  };
  const storageKey='opengenjutsu.sequence.project',recoveryKey='opengenjutsu.sequence.recovery';
  const previous=[localStorage.getItem(storageKey),localStorage.getItem(recoveryKey)];
  const originalURL=location.href,oldProject=window.OpenGenjutsuProject;
  window.OpenGenjutsuProject={ready:Promise.resolve()};history.replaceState(null,'',`?project_id=${C}`);
  function mount(){
    // Fixture markup is fixed test data, never application output.
    el('harness').innerHTML=fixture;
    return mountSequence({onSelect:(...args)=>selections.push(args),onPreview:entry=>previews.push(entry),onCompose(){},onError:message=>errors.push(message)});
  }
  const rows=()=>[...el('native-takes').children].filter(row=>row.dataset.sourceKey);
  const row=key=>rows().find(row=>row.dataset.sourceKey===key);
  const common=()=>{el('native-library-scope').value='common';el('native-library-scope').dispatchEvent(new Event('change'));};
  let seq;
  try {
    seq=mount();await seq.init(entries);
    equal(rows().map(r=>r.dataset.sourceKey),[`native:${A}`,`swap:${B}`,`native:${D}`],'project filter is typed and honors ephemeral native job links');
    equal(calls.filter(c=>c.options.method).length,0,'discovery never writes');passed.push('mixed discovery and project membership');
    common();equal(rows().length,4,'common scope includes both colliding UUIDs');
    const before=JSON.stringify(seq.state());row(`swap:${A}`).children[0].click();
    equal(previews.at(-1),entries[1],'Swap preview returns original entry');equal(JSON.stringify(seq.state()),before,'preview does not place or alter drafts');
    seq.preview(A);equal(previews.at(-1),entries[0],'legacy preview defaults native');
    seq.preview(A,'swap');equal(previews.at(-1),entries[1],'typed preview resolves UUID collision');
    equal(row(`native:${A}`).children[0].getAttribute('aria-pressed'),'false','native collision is not highlighted');
    equal(row(`swap:${A}`).children[0].getAttribute('aria-pressed'),'true','typed preview is highlighted');
    const media=row(`swap:${A}`).querySelector('img');assert(media&&media.loading==='lazy'&&media.getAttribute('src')===`/api/jobs/${A}/poster`,'Swap library uses a lazy server JPEG poster');
    assert(!row(`swap:${A}`).querySelector('video'),'Swap discovery never loads full videos');
    assert(row(`native:${A}`).querySelector('img').getAttribute('src').includes(`/takes/${A}/poster`),'native poster endpoint retained');
    assert(row(`swap:${A}`).textContent.includes('Video only'),'Swap capability is honest');passed.push('read-only typed preview and safe media');
    row(`swap:${A}`).children[1].focus();row(`swap:${A}`).children[1].click();
    equal(seq.state().placements[0].source_kind,'swap','explicit plus places Swap');
    assert(document.activeElement===row(`swap:${A}`).children[1],'plus focus survives rerender');
    const railPoster=el('board-track').querySelector('img.sequence-poster');
    assert(railPoster&&railPoster.loading==='lazy'&&railPoster.getAttribute('src')===`/api/jobs/${A}/poster`,'Swap rail uses the same lazy server JPEG');
    assert(!el('board-track').querySelector('video'),'rail never fetches full videos');
    seq.setDraft({prompt:'Keep my direction',seed:'18446744073709551615'});
    const first=seq.selected().placement_id;
    seq.place(A,null,{prompt:'Native draft'});seq.place(A,null,null,'swap');
    equal(seq.state().placements.map(p=>p.source_kind??'native'),['swap','native','swap'],'multiple placements retain source types');
    assert(!el('native-library').hidden,'placing keeps library open');
    seq.openPlacement(first);equal(selections.at(-1)[0],entries[1],'rail selection resolves typed source');
    await seq.flush();equal(saved.placements.length,3,'explicit placements reach save payload');
    equal(JSON.parse(localStorage.getItem(recoveryKey)).placements[0].source_kind,'swap','recovery keeps typed source');passed.push('explicit multiple placements, focus and recovery');
    const transfer=drag(row(`swap:${A}`),'dragstart',{});
    equal(JSON.parse(transfer.getData('text/plain')),{kind:'swap',id:A},'Swap drag is typed JSON');
    drag(el('board-track').children[0],'drop',{'text/plain':transfer.getData('text/plain')});
    equal(seq.state().placements[0].source_kind,'swap','position wrapper retains Swap type at start');
    drag(el('take-board'),'drop',{'text/plain':A});
    assert(!('source_kind' in seq.state().placements.at(-1)),'plain UUID drag remains native');
    drag(el('take-board'),'drop',{'text/plain':'{"kind":"other","id":"'+A+'"}'});
    equal(seq.state().placements.length,5,'invalid typed drop cannot place');
    seq.place(B,first,null,'swap');equal(seq.state().placements.findIndex(p=>p.take_id===B),seq.state().placements.findIndex(p=>p.placement_id===first)+1,'explicit afterId preserved');
    await seq.flush();passed.push('typed drag, native compatibility and exact-position insertion');
    seq.openPlacement(first);await seq.flush();
    seq=mount();await seq.init(entries);
    equal(seq.state().placements.length,6,'reload restores all placements');
    equal(seq.selected().source_kind,'swap','reload restores typed selection');
    equal(seq.draft().prompt,'Keep my direction','reload restores original draft');
    equal(selections.at(-1)[0],entries[1],'reload callback resolves Swap collision');
    assert(!el('native-library').hidden,'reload keeps library visible');
    equal(calls.filter(c=>c.options.method&&c.options.method!=='PATCH').length,0,'no generation or import requests');passed.push('typed save/reload with draft and project context');
    equal(errors.length,1,'only the intentional malformed drop reports an error');
    return passed;
  } finally {
    window.fetch=originalFetch;window.OpenGenjutsuProject=oldProject;history.replaceState(null,'',originalURL);
    [storageKey,recoveryKey].forEach((key,i)=>previous[i]===null?localStorage.removeItem(key):localStorage.setItem(key,previous[i]));
  }
}

// Imported by the real H3 controller harness; no replacement controller or DOM.
import assert from 'node:assert/strict';
export async function checkNativeCaptureUpgrade({el,calls,response,settle,child,base,setHandler,lastToast}) {
  el('description').value='  a tall woman  ';
  // A stale/altered hidden field cannot silently turn off capture.
  el('native-capture').value='false';
  const posts=calls.filter(([,opts])=>opts.method==='POST').length;
  setHandler(url=>url.startsWith('/api/h3/readiness')?response({ready:true}):response({}));
  await el('form').events.submit({preventDefault(){}});await settle();
  assert.equal(calls.filter(([,opts])=>opts.method==='POST').length,posts,'Old backend cannot silently accept native capture as video only');
  assert.match(lastToast(),/Native state capture is not confirmed/);
  assert.equal(el('reference').files[0].name,'character.png');
  let submitted;
  setHandler((url,opts)=>{
    if(url.startsWith('/api/h3/readiness'))return response({ready:true,native_capture_supported:true});
    if(url==='/api/h3/jobs'){submitted=opts.body;return response({job_id:child},202);}
    return response({...base,id:child,status:'error',error:'Test failure'});
  });
  await el('form').events.submit({preventDefault(){}});await settle();
  assert.equal(submitted.get('edit_prompt'),'  original\n directions  ');
  assert.equal(submitted.get('native_capture'),'true');
  assert.equal(submitted.get(el('description').name),'  a tall woman  ');
  assert.equal(submitted.getAll('reference_images').length,1);
  assert.equal(el('reference-2').disabled,true);
}

import {apiJSON,validateExport,validId} from './timeline-state.js';
const $=id=>document.getElementById(id);

export class TimelineExport {
  constructor(notify) {
    this.notify=notify;this.epoch=0;this.current=null;this.project=null;this.file=null;
    $('close-export').addEventListener('click',()=>$('timeline-export-dialog').close());
    $('timeline-export-dialog').addEventListener('close',()=>{
      if (!$('timeline-export-dialog').open) $('export-video').pause();
    });
    $('copy-export-caption').addEventListener('click',async()=>{
      try {await navigator.clipboard.writeText($('export-caption').value);notify('Caption copied. Add your MP4 when posting.');}
      catch {$('export-caption').focus();$('export-caption').select();notify('Select and copy the caption here; clipboard access is unavailable.');}
    });
    $('share-export').addEventListener('click',()=>this.share());
    $('retry-export').addEventListener('click',()=>{
      if (this.current && ['queued','running'].includes(this.current.status)) this.watch(this.current.export_id,this.epoch);
      else if (this.project) this.open(this.project);
    });
    window.addEventListener('pagehide',()=>{clearTimeout(this.timer);this.epoch++;});
  }
  async open(project) {
    if (!project?.clips.length) return;
    const epoch=++this.epoch;clearTimeout(this.timer);this.project=project;this.file=null;this.current=null;
    $('share-export').disabled=false;
    $('export-video').pause();$('export-video').removeAttribute('src');$('export-video').hidden=true;
    for (const id of ['download-export','share-export','retry-export']) $(id).hidden=true;
    $('export-caption').value=`${project.title}\nMade with OpenGenjutsu. #OpenGenjutsu`;
    $('export-status').textContent='Preparing your cut. You can close this preview while it works.';
    const dialog=$('timeline-export-dialog');if (!dialog.open) dialog.showModal();
    try {
      const value=validateExport(await apiJSON(`/api/timeline/projects/${project.project_id}/export`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:project.revision})}));
      if (epoch!==this.epoch) return;
      if (value.project_id!==project.project_id || value.revision!==project.revision) throw new Error('The export belongs to a different sequence revision.');
      try {localStorage.setItem(`opengenjutsu.timeline.export.${project.project_id}`,value.export_id);} catch {}
      this.current=value;this.paint();
      if (['queued','running'].includes(value.status)) this.watch(value.export_id,epoch);
    } catch(error) {
      if (epoch!==this.epoch) return;
      $('export-status').textContent=error.message;
      $('retry-export').hidden=false;$('retry-export').textContent='Retry export';
    }
  }
  async watch(id,epoch,attempt=0) {
    if (epoch!==this.epoch) return;
    clearTimeout(this.timer);
    try {
      const value=validateExport(await apiJSON(`/api/timeline/exports/${id}`));
      if (epoch!==this.epoch) return;
      if (value.export_id!==id || value.project_id!==this.project.project_id || value.revision!==this.project.revision) {
        throw new Error('The export identity changed. Reload before downloading.');
      }
      this.current=value;this.paint();
      if (['queued','running'].includes(value.status)) {
        if (attempt>=900) throw new Error('The export is still pending. Check its status again; it has not been resubmitted.');
        this.timer=setTimeout(()=>this.watch(id,epoch,attempt+1),1000);
      }
    } catch(error) {
      if (epoch!==this.epoch) return;
      $('export-status').textContent=error.message;
      $('retry-export').hidden=false;$('retry-export').textContent='Check export status';
    }
  }
  paint() {
    const value=this.current;
    $('retry-export').hidden=value.status!=='error';
    if (value.status==='error') {
      $('export-status').textContent=typeof value.error==='string'?value.error:'The export failed. Your sequence and original takes are unchanged.';
      $('retry-export').textContent='Retry export';return;
    }
    if (value.status!=='ready') {
      $('export-status').textContent=value.status==='queued'?'Your cut is queued for export.':'Rendering your cut. Your original takes stay untouched.';return;
    }
    $('export-status').textContent='Your cut is ready. Watch it, download the MP4, then share it your way.';
    const video=$('export-video');
    if (video.getAttribute('src')!==value.preview_url) video.src=value.preview_url;
    video.hidden=false;$('download-export').href=value.download_url;$('download-export').hidden=false;
    $('share-export').hidden=typeof navigator.share!=='function';
    $('share-export').textContent=this.file?'Share prepared file':'Prepare file sharing';
  }
  async share() {
    if (this.current?.status!=='ready') return;
    if (this.file) {
      try {await navigator.share({files:[this.file],title:this.project.title,text:$('export-caption').value});}
      catch(error) {if (error.name!=='AbortError') this.notify('File sharing did not complete. Download the MP4 instead.');}
      return;
    }
    const button=$('share-export'), id=this.current.export_id, epoch=this.epoch;
    button.disabled=true;button.textContent='Preparing file…';
    try {
      const response=await fetch(this.current.preview_url,{credentials:'same-origin',signal:AbortSignal.timeout(60000)});
      if (!response.ok || !/^video\/mp4(?:;|$)/i.test(response.headers.get('Content-Type')||'')) throw new Error('The export file could not be prepared. Download it instead.');
      const budget=50*1024*1024;
      if (Number(response.headers.get('Content-Length'))>budget) throw new Error('This export exceeds the in-browser sharing budget. Download the MP4 to share it.');
      const reader=response.body.getReader(),chunks=[];let size=0;
      try {
        while (true) {
          const {done,value}=await reader.read();if (done) break;
          size+=value.byteLength;if (size>budget) throw new Error('This export exceeds the in-browser sharing budget. Download the MP4 to share it.');
          chunks.push(value);
        }
      } finally {await reader.cancel().catch(()=>{});}
      if (!size) throw new Error('The export file is empty. Retry its status.');
      if (epoch!==this.epoch || this.current.export_id!==id) return;
      const file=new File(chunks,`opengenjutsu-${id.slice(0,8)}.mp4`,{type:'video/mp4'});
      if (!navigator.canShare?.({files:[file]})) throw new Error('File sharing is unavailable in this browser. Download the MP4 and copy your caption instead.');
      this.file=file;this.notify('File prepared. Press Share prepared file to open your device’s sharing menu.');
    } catch(error) {if (epoch===this.epoch) this.notify(error.message);}
    finally {if (epoch===this.epoch) {button.disabled=false;this.paint();}}
  }
}

import assert from 'node:assert/strict';
import {validateProject, validateExport, placements, totalDuration, clipAtTime, trimPlacement,
        movePlacement, formatTime, apiJSON} from '../src/static/timeline-state.js';
const a = 'a'.repeat(32), b = 'b'.repeat(32), c = 'c'.repeat(32);
const clip = (id, frames, fps = 24) => ({clip_id:id, take_id:id, label:'My clip', engine:'ltx25-ripple',
  width:32,height:32,fps,frames,in_frame:0,out_frame:frames,
  media_url:`/api/timeline/takes/${id}/media`, source_job_id:null});
const project = {project_id:a,title:'My cut',revision:1,created_at:1,updated_at:2,character_id:null,
  clips:[clip(b,48),clip(c,24)]};
assert.equal(validateProject(project), project);
assert.equal(totalDuration(project.clips), 3);
assert.deepEqual(clipAtTime(project.clips,2.25), {index:1,sourceTime:0.25,sequenceTime:2.25});
assert.equal(clipAtTime([],0), null);
assert.equal(clipAtTime(project.clips,99).index, 1);
assert.equal(formatTime(65.25),'1:05.25');
const trim = trimPlacement(project.clips,b,'12','36');
assert.deepEqual(trim[0], {clip_id:b,in_frame:12,out_frame:36});
assert.equal(project.clips[0].in_frame, 0); // pure draft, not an implicit mutation.
assert.deepEqual(movePlacement(project.clips,c,-1).map(x=>x.clip_id),[c,b]);
assert.deepEqual(placements(project.clips).map(x=>Object.keys(x).sort()),
  [ ['clip_id','in_frame','out_frame'], ['clip_id','in_frame','out_frame'] ]);
for (const [start,end] of [['','24'],['1.5','24'],['24','24'],['0','49'],['-1','24'],['0','1e6']]) {
  assert.throws(()=>trimPlacement(project.clips,b,start,end));
}
assert.throws(()=>trimPlacement(project.clips,a,'0','1'));
for (const patch of [{revision:true},{project_id:'../bad'}, {character_id:'http://evil'},
                     {clips:[{...project.clips[0],media_url:'https://elsewhere.invalid/video'}]},
                     {clips:[{...project.clips[0],fps:NaN}]},
                     {clips:[{...project.clips[0],out_frame:99}]},
                     {clips:[project.clips[0],project.clips[0]]}]) {
  assert.throws(()=>validateProject({...project,...patch}));
}
const status={export_id:b,project_id:a,revision:1,status:'queued',status_url:`/api/timeline/exports/${b}`,
  preview_url:null,download_url:null,error:null};
assert.equal(validateExport(status),status);
assert.throws(()=>validateExport({...status,status_url:'https://elsewhere.invalid/'}));
assert.throws(()=>validateExport({...status,status:'ready'}));
assert.equal(validateExport({...status,status:'ready',preview_url:`/api/timeline/exports/${b}/media`,
  download_url:`/api/timeline/exports/${b}/media?download=true`}).status,'ready');
const fetcher = async()=>new Response(JSON.stringify({detail:'Changed elsewhere'}), {status:409,
  headers:{'Content-Type':'application/json'}});
await assert.rejects(()=>apiJSON('/api/timeline/projects',{},fetcher),error=>error.status===409);
await assert.rejects(()=>apiJSON('https://elsewhere.invalid/api',{},fetcher));
console.log('Timeline state: frame trims, ordering, timing, strict media URLs, export states, revision errors PASS');

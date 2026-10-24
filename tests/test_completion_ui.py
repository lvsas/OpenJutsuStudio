"""Completion UI contracts: real controllers, fake DOM/HTTP, no GPU claims."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CompletionUITests(unittest.TestCase):
    def test_completion_hierarchy_and_closed_inspection(self):
        for page, prefix in [('index.html', ''), ('h3.html', 'h3-')]:
            html = (ROOT / 'src/templates' / page).read_text()
            self.assertIn('Your swap is ready', html)
            self.assertIn('Take Passport', html)
            self.assertIn('Your character. Your moment.', html)
            self.assertRegex(html, rf'id="{prefix}build-reel" class="btn btn-primary[^\"]*"')
            self.assertIn('Preview share reel', html)
            self.assertIn('Download result', html)
            self.assertRegex(html, rf'id="{prefix}return-last"[^>]*hidden')
            for id_ in ['completion-more', 'take-inspection']:
                tag = re.search(rf'<details[^>]*id="{prefix}{id_}"[^>]*>', html)
                self.assertIsNotNone(tag, id_)
                assert tag is not None
                self.assertNotRegex(tag.group(), r'\bopen\b')
            self.assertLess(html.index('/static/app.css'), html.index('/static/completion.css'))
            self.assertLess(html.index('/static/share-reel.js'), html.index('/static/' + ('app.js' if not prefix else 'h3-studio.js')))
            # Pre-generation copy is deliberately outside this post-swap change.
        css = (ROOT / 'src/static/completion.css').read_text()
        self.assertIn('prefers-reduced-motion', css)

    def test_h3_two_reference_grid_has_four_bounded_card_tracks(self):
        css = (ROOT / 'src/static/h3-studio.css').read_text()
        self.assertRegex(css, r'\[data-engine="h3"\] \.take-story-path:has\(#h3-take-reference-2-card:not\(\[hidden\]\)\)\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) auto minmax\(0,\s*1fr\) auto minmax\(0,\s*1fr\) auto minmax\(0,\s*1fr\)')
        common = (ROOT / 'src/static/app.css').read_text()
        self.assertIn('grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr)', common)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_shared_result_first_layout(self):
        result = subprocess.run(['node', '--test', 'tests/studio_result_layout_contract.mjs'],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_h3_explicit_inspection_and_two_reference_selection(self):
        result = subprocess.run(['node', '--experimental-vm-modules', '--test',
                                 'tests/h3_inspection_contract.mjs'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_ltx_completion_persistence_modal_and_stale_responses(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/static/app.js', 'utf8');
const id = 'a'.repeat(32), child = 'b'.repeat(32);
const done = {id, engine:'ltx25-ripple', status:'done', result_url:`/api/jobs/${id}/result`, source_url:`/api/jobs/${id}/source`};
const settle = async () => {for(let i=0;i<12;i++) await new Promise(r=>setImmediate(r));};
function setup(store = new Map(), handler = async () => done, blocked = false) {
  const nodes = new Map(); const events = {}; let bindings; const calls = [], opens = [];
  const node = id => {if(!nodes.has(id)) nodes.set(id, {hidden:true, files:[], disabled:false, src:'', textContent:'', events:{}, classList:{add(){},remove(){}},
    addEventListener(k,fn){this.events[k]=fn;},setAttribute(){},removeAttribute(k){delete this[k];}, pause(){}, load(){}}); return nodes.get(id);};
  const context = {console, URL:{revokeObjectURL(){}}, CustomEvent: class {constructor(type,init){this.type=type;this.detail=init.detail;}},
    document:{querySelector:s=>node(s.slice(1))}, navigator:{clipboard:{writeText:async()=>{}}},
    localStorage:{getItem(k){if(blocked)throw Error('blocked');return store.get(k);},setItem(k,v){if(blocked)throw Error('blocked');store.set(k,v);},removeItem(k){if(blocked)throw Error('blocked');store.delete(k);}},
    fetch:async(url,opts)=>{calls.push([url,opts]);const data=await handler(url,opts);if(data instanceof Response)return data;return {ok:true,json:async()=>data};},
    window:{setTimeout:()=>1,clearTimeout(){},addEventListener(k,fn){events[k]=fn;},dispatchEvent(e){events[e.type]?.(e);},
      OpenGenjutsuShare:{open:opts=>opens.push(opts)},
      OpenGenjutsuStudio:{bindFileDropTargets(){}, formatDuration:()=>'',replaceObjectUrl:()=> 'blob:new',showToast(){},renderProgress(){},bindSubmission(opts){bindings=opts;return {refresh(){}};}}}};
  vm.createContext(context);vm.runInContext(source,context);
  return {nodes,node,events,calls,opens,context,get bindings(){return bindings;}};
}
(async()=>{
 const store = new Map([['opengenjutsu.ltx.completed-job',id]]);
 const ui=setup(store); await settle();
 assert.equal(ui.node('result-actions').hidden,false,'refresh must restore the finished canvas');
 ui.node('build-reel').events.click(); await settle();
 assert.equal(ui.opens[0].jobId,id);assert.equal(ui.opens[0].resultUrl,done.result_url);
 assert.equal(ui.opens[0].returnFocus,ui.node('build-reel'));
 assert.equal(ui.calls.some(([url,opts])=>opts?.method==='POST'),false,'preview delegates to shared modal, never builds/downloads directly');
 assert.ok(ui.calls.some(([url,opts])=>url===done.result_url && opts?.headers?.Range==='bytes=0-0'),'availability uses the existing GET range route, not unsupported HEAD');
 ui.node('video').files=[{}];ui.node('video').events.change();
 assert.equal(ui.node('return-last').hidden,false,'changing source keeps a visible path to last success');
 ui.bindings.onBegin();ui.bindings.onFailure();
 assert.equal(store.get('opengenjutsu.ltx.completed-job'),id,'new failure must not erase last success');
 await ui.node('return-last').events.click();await settle();
 assert.equal(ui.node('result-actions').hidden,false);
 const failedStore=new Map([['opengenjutsu.ltx.completed-job',id],['opengenjutsu.ltx.current-job',child]]);
 const failed=setup(failedStore,async()=>({...done,id:child,status:'error',result_url:null,error:'New take failed'}));await settle();
 assert.equal(failed.node('return-last').hidden,false);
 assert.equal(failed.node('return-last').disabled,false);
 assert.equal(failedStore.get('opengenjutsu.ltx.completed-job'),id);
 let resolve;const stale=setup(new Map([['opengenjutsu.ltx.completed-job',id]]),()=>new Promise(r=>resolve=r));
 stale.node('video').files=[{}];stale.node('video').events.change();resolve(done);await settle();
 assert.equal(stale.node('result-actions').hidden,true,'late restoration must not overwrite new input');
 const invalid=setup(new Map([['opengenjutsu.ltx.completed-job',id]]),async()=>({...done,engine:'minimax-h3'}));await settle();
 assert.equal(invalid.node('result-actions').hidden,true,'wrong engine must never restore');
 const missing=setup(new Map([['opengenjutsu.ltx.completed-job',id]]),async()=>({...done,result_url:null}));await settle();
 assert.equal(missing.node('result-actions').hidden,true,'done without result is not a completed canvas');
 const gone=setup(new Map([['opengenjutsu.ltx.completed-job',id]]),async(url,opts)=>opts?.headers?.Range ? new Response('',{status:404}) : done);await settle();
 assert.equal(gone.node('result-actions').hidden,true,'a missing artifact must not restore a broken finished canvas');
 const mismatch=setup(new Map([['opengenjutsu.ltx.completed-job',id]]),async()=>({...done,id:child}));await settle();
 assert.equal(mismatch.node('result-actions').hidden,true,'server job identity must match storage');
 const privateUI=setup(new Map(),async()=>done,true);privateUI.bindings.onBegin();
 privateUI.bindings.onQueued({job_id:id,job:done});await settle();
 assert.equal(privateUI.node('result-actions').hidden,false,'storage denial must not break generation');
 console.log('LTX completion contracts passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('LTX completion contracts passed', result.stdout)


if __name__ == '__main__':
    unittest.main()

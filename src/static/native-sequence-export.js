/* Export the saved native rail, never the library or hidden legacy cut. */
import {getTimelineExport} from './timeline-export-ui.js';
export function mountNativeExport({sequence,button,notify}) {
  let opening=false;
  function update() {
    button.disabled=opening||!sequence.editable()||!sequence.state().placements.length;
  }
  button.addEventListener('click',async()=>{
    if(button.disabled)return;
    const requested=sequence.state();opening=true;update();
    try {
      await sequence.flush();
      const saved=sequence.state();
      if(!sequence.editable()||!saved.project_id||!saved.placements.length
          ||(requested.project_id&&saved.project_id!==requested.project_id)
          ||JSON.stringify(saved.placements)!==JSON.stringify(requested.placements))
        throw new Error('Your sequence changed before export. Review it and try again; nothing was exported.');
      await getTimelineExport(notify).open(saved,'native',notify);
    } catch(error) {notify(error.message||'The sequence could not be exported. Your takes are unchanged.');}
    finally {opening=false;update();}
  });
  update();return {update};
}

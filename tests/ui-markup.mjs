import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const templates=new URL('../src/templates/',import.meta.url);
export function readMarkup(name='timeline.html'){
  return readFileSync(fileURLToPath(new URL(name,templates)),'utf8').replace('<!-- shared-export-dialog -->',readFileSync(fileURLToPath(new URL('export-dialog.html',templates)),'utf8'));
}

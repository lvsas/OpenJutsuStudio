import assert from 'node:assert/strict';
import {applyCharacterReference, validCharacterId} from '../src/static/character-handoff.js';

const id = 'a'.repeat(32);
class Input extends EventTarget { files = []; disabled = false; }
globalThis.DataTransfer = class { files = []; items = {add: file => this.files.push(file)}; };
const messages = [];
let calls = [];
const response = () => new Response(new Uint8Array([137,80,78,71,13,10,26,10]), {
  headers: {'Content-Type': 'image/png'},
});
const fetcher = async (url, options) => { calls.push({url, options}); return response(); };
const notify = text => messages.push(text);
assert.equal(validCharacterId(id), true);
for (const value of ['', '../bad', 'a'.repeat(31), id.toUpperCase(), null, {}]) assert.equal(validCharacterId(value), false);
for (const search of ['', '?character_id=../../secret', `?character_id=${id}&project_id=../../bad`, `?character_id=${id}&project_id=${id}&project_id=${id}`, `?character_id=${id}&character_id=${id}`]) {
  calls = [];
  assert.equal(await applyCharacterReference({search, input: new Input(), fetcher, notify}), false);
  assert.equal(calls.length, 0);
}
const input = new Input();
let changed = 0;
input.addEventListener('change', () => changed++);
assert.equal(await applyCharacterReference({search: `?character_id=${id}`, input, fetcher, notify}), true);
assert.equal(input.files[0].type, 'image/png');
assert.equal(changed, 1);
assert.equal(calls.length, 1);
assert.equal(calls[0].url, `/api/characters/jobs/${id}/image`);
assert.equal(calls[0].options.method, undefined); // GET only; never generation.
assert.equal(calls[0].options.credentials, 'same-origin');
// Existing manual selection and a busy studio are not overwritten.
assert.equal(await applyCharacterReference({search: `?character_id=${id}`, input, fetcher, notify}), false);
assert.equal(changed, 1);
assert.equal(await applyCharacterReference({search: `?character_id=${id}`, input: new Input(), fetcher, notify, isBusy: () => true}), false);
// A manual selection made while the GET is outstanding wins the race.
const newer = new Input();
assert.equal(await applyCharacterReference({search: `?character_id=${id}`, input: newer, notify,
  fetcher: async () => { newer.files = ['manual']; return response(); }}), false);
assert.deepEqual(newer.files, ['manual']);
for (const bad of [new Response('', {status: 404}), new Response('<html>not image</html>', {
  headers: {'Content-Type': 'text/html'},
}), new Response('', {headers: {'Content-Type': 'image/png'}}), new Response('x', {
  headers: {'Content-Type': 'image/png', 'Content-Length': String(40 * 1024 * 1024)},
})]) {
  const untouched = new Input();
  assert.equal(await applyCharacterReference({search: `?character_id=${id}`, input: untouched,
    fetcher: async () => bad, notify}), false);
  assert.equal(untouched.files.length, 0);
}
// A false Content-Length cannot bypass the actual streamed-body budget.
const large = new Input();
assert.equal(await applyCharacterReference({search: `?character_id=${id}`, input: large, notify,
  fetcher: async () => new Response(new Uint8Array(33 * 1024 * 1024), {
    headers: {'Content-Type': 'image/png', 'Content-Length': '1'},
  })}), false);
assert.equal(large.files.length, 0);
console.log('Character handoff: ID validation, GET-only file transfer, race protection, failed/oversized media PASS');

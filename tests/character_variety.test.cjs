/* Pure configuration/builder contracts; no DOM, network, GPU or persistent data. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/static/character.js'),'utf8');
const literal=source.match(/const LOOKS = (\[[\s\S]*?\n  \]);/)[1];
const looks=vm.runInNewContext(literal);
const builder=source.match(/function buildDirection\(\) \{[\s\S]*?\n  \}/)[0];
const direction=index=>vm.runInNewContext(`(${builder})()`,{LOOKS:looks,pick:list=>list[index]});

test('six coherent proposals include three women and distinct hair/body/clothes',()=>{
  assert.equal(looks.length,6);
  assert.equal(looks.filter(l=>l.being==='woman').length,3);
  assert.equal(looks.filter(l=>l.being==='man').length,2);
  assert.equal(looks.filter(l=>l.being==='non-binary person').length,1);
  for(const field of ['role','build','hair','face','outfit','attitude']){
    assert.equal(new Set(looks.map(l=>l[field])).size,6,field+' must offer real variety');
    for(const look of looks)assert.ok(typeof look[field]==='string'&&look[field].length<=300,field);
  }
});

test('the shipped builder consumes presentation and face, not just labels',()=>{
  for(let i=0;i<looks.length;i++){
    const text=direction(i),look=looks[i];
    assert.match(text,new RegExp('^An original adult '+look.being+','));
    for(const key of ['role','build','hair','face','outfit','attitude'])assert.ok(text.includes(look[key]),key);
    assert.ok(text.length<=2000);
    assert.doesNotMatch(text,/caricature|tiny waist|outsized head|holding|carrying|photograph|studio|portrait/i);
    assert.doesNotMatch(look.hair,/moustache|\bface\b/i,'hair override must not secretly override the face');
  }
});

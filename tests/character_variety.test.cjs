/* Pure configuration/builder contracts; no DOM, network, GPU or persistent data. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/static/character.js'),'utf8');
const literal=source.match(/const LOOKS = (\[[\s\S]*?\n  \]);/)[1];
const looks=vm.runInNewContext(literal);
const builder=source.match(/function buildDirection\([^)]*\) \{[\s\S]*?\n  \}/)[0];
const direction=index=>vm.runInNewContext(`(${builder})(look)`,{look:looks[index],LOOKS:looks,pick:list=>list[index]});

test('six coherent proposals include three women and distinct hair/body/clothes',()=>{
  assert.equal(looks.length,6);
  assert.equal(looks.filter(l=>l.being==='woman').length,3);
  assert.equal(looks.filter(l=>l.being==='man').length,2);
  assert.equal(looks.filter(l=>l.being==='non-binary person').length,1);
  assert.deepEqual(Array.from(looks,l=>l.primary_axis),['hair','build','face','face','build','hair']);
  for(const look of looks)assert.deepEqual(Object.keys(look).sort(),['being','role','build','hair','face','outfit','attitude','primary_axis'].sort());
  for(const field of ['being','role','build','hair','face','outfit','attitude']){
    if(field!=='being')assert.equal(new Set(looks.map(l=>l[field])).size,6,field+' must offer real variety');
    for(const look of looks)assert.ok(typeof look[field]==='string'&&look[field].trim()&&look[field].length<=300,field);
  }
});

test('every tuple has an emphatic physical signature, not normalized fashion anatomy',()=>{
  const signatures=[/shoulder.width.*copper|copper.*(?:shoulder.width|wider than both shoulders)/i,/towering.*crest/i,/enormous.*halo/i,/waist.length.*cascade/i,/three.*oversized.*waves/i,/enormous.*fan/i];
  for(let i=0;i<looks.length;i++){
    assert.match(looks[i].hair,signatures[i]);
    assert.match(looks[i].hair,/strands/i,'architectural volume must remain actual hair');
    assert.doesNotMatch(looks[i].build,/ordinary|normal-sized|realistically proportioned|natural.length/i);
    assert.doesNotMatch(looks[i].outfit,/\bplain\b|simple black shoes|simple white shoes/i,'the creator rejected interchangeable plain basics');
    assert.match(looks[i].outfit,/collar|lapels|cropped|high-waisted|high waist/i,'each outfit needs a deliberate cut');
    assert.match(looks[i].outfit,/flared|flares|wide-leg|extra-wide|platform|block-heel|heeled/i,'styling must have a visible silhouette');
  }
  assert.ok(looks.some(l=>/massive.*muscular/i.test(l.build)));
  assert.ok(looks.some(l=>/heavy.*belly/i.test(l.build)));
  assert.ok(looks.some(l=>/very tall.*lean/i.test(l.build)));
});


test('every outfit names a concrete material and construction detail, not generic fashion',()=>{
  for(const look of looks){
    assert.match(look.outfit,/velour|velvet|brocade|quilted|ribbed-knit|mohair/);
    assert.match(look.outfit,/collar|lapels|buttons|zips|piping|sleeves/);
    assert.doesNotMatch(look.outfit,/holding|carrying|clutching|hat|mask|costume/);
  }
});

test('shuffle has eighteen extravagant coherent wardrobes, with short labels and safe exact facts',()=>{
  const wardrobes=vm.runInNewContext(source.match(/const WARDROBES = (\[[\s\S]*?\n  \]);/)[1]);
  assert.equal(wardrobes.length,looks.length);
  assert.equal(wardrobes.flat().length,18);
  assert.equal(new Set(wardrobes.flat().map(entry=>entry.outfit)).size,18);
  for(const variants of wardrobes){
    assert.equal(variants.length,3);
    for(const entry of variants){
      assert.ok(entry.label.length<=48);
      assert.ok(entry.outfit.length<=300);
      assert.match(entry.outfit,/mohair|vinyl|jacquard|quilted|denim|tulle|brocade|neoprene|knit|lurex|taffeta|faux-fur|satin/);
      assert.doesNotMatch(entry.outfit,/\bplain\b|holding|carrying|clutching/);
    }
  }
});

test('the copper signature is one low lateral mass of actual hair, not a tall block or accessory',()=>{
  assert.match(looks[0].hair,/copper/i);
  assert.match(looks[0].hair,/low.*(?:horizontal|lateral)|(?:horizontal|lateral).*low/i);
  assert.match(looks[0].hair,/wider than both shoulders/i);
  assert.match(looks[0].hair,/continuous.*(?:mass|hair)|(?:mass|hair).*continuous/i);
  assert.match(looks[0].hair,/scalp.*strands|strands.*scalp/i);
  assert.doesNotMatch(looks[0].hair,/inverted trapezoid|flat top|\bbob\b|wig|buns?|ornament|headdress/i);
});

test('grey hair suggestions describe natural strands rather than metal',()=>{
  assert.ok(looks.some(l=>/natural grey hair.*individual matte strands/.test(l.hair)));
  for(const look of looks)assert.doesNotMatch(look.hair,/\bsilver\b/i);
});

test('the shipped builder consumes presentation and face, not just labels',()=>{
  for(let i=0;i<looks.length;i++){
    const text=direction(i),look=looks[i];
    const article=/^[aeiou]/i.test(look.role)?'an':'a';
    assert.equal(text,`An original adult ${look.being}, ${article} ${look.role}: ${look.build}, ${look.hair}, ${look.face}, wearing ${look.outfit}, ${look.attitude}.`);
    assert.match(text,new RegExp('^An original adult '+look.being+','));
    for(const key of ['role','build','hair','face','outfit','attitude'])assert.ok(text.includes(look[key]),key);
    assert.ok(text.length<=2000);
    assert.doesNotMatch(text,/caricature|tiny waist|outsized head|holding|carrying|photograph|studio|portrait/i);
    assert.doesNotMatch(look.hair,/moustache|\bface\b/i,'hair override must not secretly override the face');
  }
});

test('canonical builder uses its explicit snapshot and the role initial for a/an',()=>{
  const look={...looks[0],role:'inventive archivist'};
  const text=vm.runInNewContext(`(${builder})(look)`,{look,LOOKS:looks,pick:()=>looks[1]});
  assert.ok(text.includes(', an inventive archivist:'));
  assert.ok(text.includes(look.hair));
  assert.ok(!text.includes(looks[1].role));
});

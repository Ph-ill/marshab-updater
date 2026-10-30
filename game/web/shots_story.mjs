// Screenshot-only asset policy. Structural schema values are allowlisted;
// all other strings (including new fields, short titles and single words) redact.
export const HIDDEN='Story text hidden for review.';
export function redactStory(asset,value){
  if(!['text.json','engage.json'].includes(asset))throw Error('Unknown screenshot asset');
  function keep(path){
    if(asset==='text.json')return /^(pack|crew\.\d+|ships\.\d+|voice\.\d+|axes\.\d+|res\.\d+)$/.test(path);
    return /^(patches|arts)\.\d+\.id$|^jobs\.\d+\.out\.\d+\.art$|^badges\.\d+\.1$/.test(path);
  }
  function visit(x,path=''){
    if(typeof x==='string')return keep(path)?x:HIDDEN;
    if(Array.isArray(x))return x.map((v,i)=>visit(v,path?path+'.'+i:''+i));
    if(x&&typeof x==='object')return Object.fromEntries(Object.entries(x).map(([k,v])=>[k,visit(v,path?path+'.'+k:k)]));
    return x;
  }
  return visit(value);
}
// No story values in assertion diagnostics, console output, or files.
export function assertNoStory(dom,strings){
  if(strings.some(s=>s&&dom.includes(s)))throw Error('Story redaction failed before capture');
}
export function endingTitles(text){return text.cards.flatMap(c=>c.ti?[c.ti]:[])}

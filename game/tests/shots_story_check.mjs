import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {redactStory,assertNoStory,endingTitles,HIDDEN} from '../web/shots_story.mjs';
let redact=redactStory;
// Allows the identical checks to run against the review's pre-fix implementation.
if(process.env.LEGACY_SHOTS){
  const src=fs.readFileSync(process.env.LEGACY_SHOTS,'utf8');
  const legacy=src.match(/const blank=(.*);\n/)[1];
  const c=vm.createContext({});vm.runInContext('var blank='+legacy,c);
  redact=(_,x)=>c.blank(x);
}
const text=JSON.parse(fs.readFileSync(new URL('../build/text.json',import.meta.url),'utf8'));
const titles=endingTitles(text);
assert.ok(titles.length>0,'real ending title coverage');
const clean=redact('text.json',text);
// Assert booleans only: a failing runner must never print an original story value.
assert.ok(!titles.some(t=>JSON.stringify(clean).includes(t)),'known ending titles are redacted');
assert.ok(clean.cards.every(c=>c.t===HIDDEN&&(!c.ti||c.ti===HIDDEN)&&c.o.every(o=>o.every(s=>s===HIDDEN))),'all card fields redacted');
assert.ok(JSON.stringify(clean.crew)===JSON.stringify(text.crew),'crew schema retained');
assert.ok(JSON.stringify(clean.reread)===JSON.stringify(text.reread),'numeric references retained');
const sample={cards:[{t:'X',ti:'Y',o:[['Z','W']]}],epi:{story:[[1,'Q']],coda:{name:'R'}},future:'S'};
assert.ok(!['X','Y','Z','W','Q','R','S'].some(s=>JSON.stringify(redact('text.json',sample)).includes('"'+s+'"')),'short single words and unknown fields redact');
const engage=JSON.parse(fs.readFileSync(new URL('../build/engage.json',import.meta.url),'utf8'));
const safeEngage=redact('engage.json',engage);
assert.ok(safeEngage.jobs.every(j=>j.l===HIDDEN&&j.t===HIDDEN&&j.out.every(o=>o.t===HIDDEN)),'engagement stories redact');
assert.ok(JSON.stringify(safeEngage.res)===JSON.stringify(engage.res),'resolver indices retained');
assert.doesNotThrow(()=>assertNoStory(JSON.stringify(clean),titles));
let rejected=false;try{assertNoStory(titles[0],titles)}catch(e){rejected=e.message==='Story redaction failed before capture'}
assert.ok(rejected,'DOM guard rejects real title without diagnostic disclosure');
console.log('screenshot story schema and real ending titles PASS');

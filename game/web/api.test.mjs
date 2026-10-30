import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const app=readFileSync(new URL('./app.html',import.meta.url),'utf8');
const source=app.slice(app.indexOf('async function api('),app.indexOf('// ---- live updates:'));
function phone(replies){
  const calls=[],delays=[],routes=[];
  const c=vm.createContext({tok:'crew-token',me:2,DQ:'',Date,Error,Promise,
    go:r=>routes.push(r),setTimeout(fn,ms){delays.push(ms);fn()},
    fetch:async(path,options)=>{calls.push([path,options]);const [status,header='',body={ok:true}]=replies[Math.min(calls.length-1,replies.length-1)];return {status,ok:status===200,headers:{get:()=>header},json:async()=>body}}});
  vm.runInContext(source,c);
  return {run:s=>vm.runInContext(s,c),calls,delays,routes};
}
test('admission 503 retries GET and POST with unchanged token/body then returns success',async()=>{
  for(const expression of ['api("/api/state")','api("/api/logout",{ok:true})']){
    const p=phone([[503,'1'],[200]]);
    assert.equal((await p.run(expression)).ok,true);
    assert.equal(p.calls.length,2);assert.deepEqual(p.delays,[1000]);
    assert.equal(p.calls[0][1].headers['X-Crew-Token'],'crew-token');
    assert.equal(p.calls[0][1].body,p.calls[1][1].body);
  }
});
test('safe-mode/story 503 without admission header is not retried',async()=>{
  const p=phone([[503,'',{safe:true,err:'story unavailable'}]]);
  await assert.rejects(p.run('api("/api/state")'),e=>e.status===503&&e.j.safe);
  assert.equal(p.calls.length,1);assert.equal(p.delays.length,0);
});
test('401 after admission retry still revokes token and routes to sign-in',async()=>{
  const p=phone([[503,'1'],[401]]);
  await assert.rejects(p.run('api("/api/state")'),/signed out/);
  assert.equal(p.run('tok'),'');assert.deepEqual(p.routes,['hello']);
});
test('ordinary write refusals are never replayed',async()=>{
  for(const status of [400,403,409,429,500]){
    const p=phone([[status,'1']]);
    await assert.rejects(p.run('api("/api/vote",{card:1,opt:0})'),e=>e.status===status);
    assert.equal(p.calls.length,1);
  }
});
test('admission retries are bounded and finally report the real 503',async()=>{
  const p=phone([[503,'1']]);
  await assert.rejects(p.run('api("/api/state")'),e=>e.status===503);
  assert.equal(p.calls.length,90);assert.equal(p.delays.length,89);
});

const live=readFileSync(new URL('./live.js',import.meta.url),'utf8');
function hailPhone(){
  const calls=[],timers=[],paint=[];let answer;
  const c=vm.createContext({tok:'crew-token',Promise,
    api:async path=>{calls.push(path);return new Promise(r=>{answer=r})},
    setTimeout(fn){timers.push(fn);return timers.length},clearTimeout(){},
    lvPaint:()=>paint.push(true)});
  vm.runInContext(live.slice(live.indexOf('let LV='),live.indexOf('function lvPaint(')),c);
  return {run:s=>vm.runInContext(s,c),calls,timers,paint,
    answer:()=>answer({out:[{st:0}],in:[],peers:[],lv:1})};
}
test('Hail reads are single-flight and logout drains before revoking the token',async()=>{
  const p=hailPhone();
  const first=p.run('lvLoad()');
  assert.equal(p.run('lvLoad()'),first);
  // Exercise the actual sign-out branch, not a test implementation of its ordering.
  const logout=app.slice(app.indexOf('  if(D.out){'),app.indexOf('  if(D.led){'));
  p.run('globalThis.D={out:1};globalThis.ws=null;globalThis.poll=0;globalThis.go=()=>{};globalThis.clearInterval=()=>{}');
  let finished=false;
  const stop=p.run('(async()=>{'+logout+'})()').then(()=>{finished=true});
  await Promise.resolve();
  await p.run('lvLoad()');
  assert.deepEqual(p.calls,['/api/live']);
  assert.equal(finished,false);
  p.answer();await first;
  // The logout request now starts; resolve it too.
  for(let i=0;i<10&&p.calls.length<2;i++)await Promise.resolve();
  assert.deepEqual(p.calls,['/api/live','/api/logout']);
  p.answer();await stop;
  assert.equal(p.run('tok'),'');
  assert.equal(p.run('LV'),null);
  assert.equal(p.timers.length,0);assert.equal(p.paint.length,0);
  await p.run('lvLoad()');assert.equal(p.calls.length,2);
});
test('a fresh sign-in can load Hail after logout; stale responses cannot paint it',async()=>{
  const p=hailPhone();
  const old=p.run('lvLoad()');
  p.run('tok="new-token"');p.answer();await old;
  assert.equal(p.run('LV'),null);assert.equal(p.paint.length,0);
  const next=p.run('lvLoad()');p.answer();await next;
  assert.equal(p.run('LV.lv'),1);assert.equal(p.paint.length,1);
  assert.equal(p.calls.length,2);
});

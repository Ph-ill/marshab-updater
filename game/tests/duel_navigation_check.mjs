// Exercise the actual duel renderer without a browser or server.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=process.env.DUEL_SOURCE?fs.readFileSync(process.env.DUEL_SOURCE,'utf8'):fs.readFileSync(new URL('../web/duel.js',import.meta.url),'utf8');
const elements={v:{innerHTML:''}};
let dockHtml='';
const listeners={},posts=[],prompts=[];
const c=vm.createContext({console,document:{addEventListener(t,f){listeners[t]=f},querySelector(){return null}},
  route:"duel/0",tok:1,api:async(path,body)=>{posts.push(body)},confirm:t=>{prompts.push(t);return true},lvLoad:async()=>{},go(){},
  home(){},lvPaint(){},view(){},shipTop(){},$:id=>elements[id],
  dock:(html,tabs)=>{dockHtml=html+(tabs?'navigation':'')},
  h:String,nm:i=>'Crew '+i,portrait:()=>'',N:2,S:{here:1,cond:[0,0]},
  lvPeer:()=>null,lvOld:()=>false,lvOff:()=>false,lvNear:()=>'',lvAgo:()=>'',LV:null});
vm.runInContext(source,c);
const states=['loading','pick','missing','draft','invited','wait','active','reveal','done','cheat','version','busy','declined','called'];
for(const state of states)for(const busy of [false,true]){
  c.LV=state==='loading'?null:{duel:state==='missing'?[]:[{to:0,s:state,shots:[],incoming:[],record:[0,0]}]};
  vm.runInContext(`DU_BUSY=${busy};duScreen(${state==='pick'?'null':'0'})`,c);
  if(state==='draft')assert.match(elements.v.innerHTML,/data-duact=discard/,'draft has discard');
  else assert.doesNotMatch(elements.v.innerHTML,/data-duact=discard/,'only drafts have discard');
  assert.match(dockHtml,/<button\b[^>]*data-go=["']?home\b[^>]*>\s*<span>Home<\/span>/,state+' has an accessible Home button');
  assert.doesNotMatch(dockHtml,/<button\b[^>]*data-go=["']?home\b[^>]*disabled/,state+' Home stays enabled');
}
console.log('duel navigation: all 14 states, idle and busy PASS');
for(const state of ['draft','invited']){
  c.LV={duel:[{id:'aa01',to:0,s:state},{id:'bb02',to:2,s:'draft'}]};
  vm.runInContext('DU_BUSY=false;DU_TO=null;duScreen(0);DU_POS=[[0,0],[12,0],[35,0]];duScreen(2);duScreen(0)',c);
  assert.equal(vm.runInContext('JSON.stringify(DU_POS)',c),'[[0,0],[12,0],[35,0]]',state+' A -> B -> A preserves placement');
  c.LV.duel[0].id='cc03';
  vm.runInContext('duScreen(0)',c);
  assert.equal(vm.runInContext('JSON.stringify(DU_POS)',c),'[null,null,null]','replacement ID has independent placement');
}
console.log('duel placement: draft and invitation cross-duel navigation PASS');
const fleet=[[0,1,2],[12,13],[35]];
c.LV={duel:[{id:'reveal',to:0,s:'active',their:fleet,layout:fleet,shots:[[1,0,1]],incoming:[],record:[0,0]}]};
vm.runInContext('duScreen(0)',c);
const firstGrid=()=>elements.v.innerHTML.split('class="du-grid ')[1].split('</div>')[0];
assert.doesNotMatch(firstGrid(),/du-cell ship/,'opponent unshot cells hidden before completion');
c.LV.duel[0].s='done';
vm.runInContext('duScreen(0)',c);
assert.equal((firstGrid().match(/du-cell ship/g)||[]).length,5,'all previously unshot opponent ship cells revealed');
console.log('duel reveal: pre-end masking and previously unshot cells PASS');
for(const [state,turn,pending,p] of [['wait',false,false,null],['active',true,false,null],['active',false,false,null],['active',false,true,7],['reveal',false,false,null],['done',false,false,null]]){
  c.LV={duel:[{id:'labels',to:0,s:state,turn,pending,p,shots:[],incoming:[],record:[0,0]}]};
  vm.runInContext('duScreen(0)',c);
  const labels=Array.from(elements.v.innerHTML.matchAll(/role=group aria-label="([^"]+)"/g),m=>m[1]);
  assert.deepEqual(labels,['Opponent field','Your field'],`${state}, turn=${turn}, pending=${pending}: field ownership is independent of interaction`);
}
for(const state of ['draft','invited']){
  c.LV={duel:[{id:'placement-label',to:0,s:state}]};
  vm.runInContext('duScreen(0)',c);
  assert.match(elements.v.innerHTML,/role=group aria-label="Your field"/,'placement field identifies your ownership');
}
console.log('duel labels: placement, waiting, both turns, pending, reveal and completion PASS');
// Call it is for a crewmate who stopped moving, never on your own turn (review 0.3.1-4 #8).
for(const turn of [true,false]){
  c.LV={duel:[{id:'call',to:0,s:'active',turn,shots:[],incoming:[],record:[0,0]}]};
  vm.runInContext('duScreen(0)',c);
  assert.match(elements.v.innerHTML,/data-duact=resign/,'resign always offered in a live duel');
  (turn?assert.doesNotMatch:assert.match)(elements.v.innerHTML,/data-duact=call/,`Call it ${turn?'hidden on':'offered off'} your turn`);
}
console.log('duel Call it: hidden on your own turn PASS');
// Resign only where the board takes it (review 0.3.1-6 #2, #3): never on the reveal
// screen; before anyone joined, the button withdraws the invitation instead.
// Withdraw is its own action, so a stale page can't turn it into a resignation, and an
// unanswered invitation has no Call it: the board puts it away at 3 days (review 0.3.1-7 #1, #4).
for(const [state,act,label,call] of [['active','resign','Resign',true],['wait','withdraw','Withdraw invitation',false],['reveal',null,null,true]]){
  c.LV={duel:[{id:'resign',to:0,s:state,turn:false,shots:[],incoming:[],record:[0,0]}]};
  vm.runInContext('duScreen(0)',c);
  const m=elements.v.innerHTML.match(/data-duact=(resign|withdraw)><span>([^<]*)</);
  assert.deepEqual(m?[m[1],m[2]]:null,act?[act,label]:null,`${state}: ${label||'no resign or withdraw'}`);
  (call?assert.match:assert.doesNotMatch)(elements.v.innerHTML,/data-duact=call/,`${state}: Call it ${call?'offered':'hidden'}`);
}
for(const [act,prompt] of [['withdraw','Withdraw your invitation? Nothing is recorded.'],['resign','Resign this duel? This counts as a loss.']]){
  c.LV={duel:[{id:'post',to:0,s:act==='withdraw'?'wait':'active',turn:false,shots:[],incoming:[],record:[0,0]}]};
  vm.runInContext('DU_BUSY=false;DU_TO=0;duScreen(0)',c);
  posts.length=prompts.length=0;
  await listeners.click({target:{closest:()=>({disabled:false,dataset:{duact:act}})}});
  assert.deepEqual([prompts,posts.map(b=>b.action)],[[prompt],[act]],`${act}: confirms and posts its own action`);
}
// Ended invitations say what happened and never read as waiting to meet (review 0.3.1-7 #3).
for(const [s,wd,text] of [['called',1,'Invitation withdrawn'],['called',2,'Crew 0 withdrew the invitation'],['called',undefined,'Duel put away'],['declined',undefined,'Invitation declined']]){
  c.LV={duel:[{id:'ended',to:0,s,wd,n:0,t:null,shots:[],incoming:[],record:[0,0]}]};
  vm.runInContext('duScreen(0)',c);
  assert.match(elements.v.innerHTML,new RegExp('role=status>'+text+'<'),`${s}/${wd}: ${text}`);
  assert.doesNotMatch(elements.v.innerHTML,/Waiting for your ships to meet|Arrived|On its way/,`${s}/${wd}: no arrival line`);
}
c.LV={duel:[{id:'open',to:0,s:'wait',n:0,t:null,shots:[],incoming:[],record:[0,0]}]};
vm.runInContext('duScreen(0)',c);
assert.match(elements.v.innerHTML,/Waiting for your ships to meet/,'open invitation still waits to meet');
// A stamp the board can't vouch for (t null after a move) never reads as waiting to meet.
c.LV={duel:[{id:'tu',to:0,s:'active',n:1,t:null,turn:false,shots:[],incoming:[[1,0,0]],record:[0,0]}]};
vm.runInContext('duScreen(0)',c);
assert.doesNotMatch(elements.v.innerHTML,/Waiting for your ships to meet|Arrived/,'move with an unknown time shows no age');
console.log('duel Resign: hidden in reveal, withdraw before joining, withdrawn and ended copy PASS');
// The board refuses a rematch while the ended duel's END or REVEAL is still queued, so the
// ended screen says why instead of offering a Rematch that would only be refused (review 0.3.1-8 #4).
for(const pending of [false,true]){
  c.LV={duel:[{id:'rematch',to:0,s:'done',why:2,win:true,pending,n:0,t:null,shots:[],incoming:[],record:[1,0]}]};
  vm.runInContext('duScreen(0)',c);
  (pending?assert.doesNotMatch:assert.match)(dockHtml,/data-dunew=0><span>Rematch</,`pending=${pending}: Rematch ${pending?'hidden':'offered'}`);
  (pending?assert.match:assert.doesNotMatch)(elements.v.innerHTML,/Your last move is still on its way to Crew 0\. Rematch opens after your ships meet\./,`pending=${pending}: reason ${pending?'shown':'absent'}`);
  assert.match(dockHtml,/data-go=home/,`pending=${pending}: Home stays`);
}
console.log('duel Rematch: waits for a queued END or REVEAL PASS');

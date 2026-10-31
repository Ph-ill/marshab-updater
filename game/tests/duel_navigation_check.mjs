// Exercise the actual duel renderer without a browser or server.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=process.env.DUEL_SOURCE?fs.readFileSync(process.env.DUEL_SOURCE,'utf8'):fs.readFileSync(new URL('../web/duel.js',import.meta.url),'utf8');
const elements={v:{innerHTML:''}};
let dockHtml='';
const c=vm.createContext({console,document:{addEventListener(){},querySelector(){return null}},
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
for(const [state,label] of [['active','Resign'],['wait','Withdraw invitation'],['reveal',null]]){
  c.LV={duel:[{id:'resign',to:0,s:state,turn:false,shots:[],incoming:[],record:[0,0]}]};
  vm.runInContext('duScreen(0)',c);
  const m=elements.v.innerHTML.match(/data-duact=resign><span>([^<]*)</);
  assert.equal(m?m[1]:null,label,`${state}: resign button ${label||'hidden'}`);
  assert.match(elements.v.innerHTML,/data-duact=call/,`${state}: Call it still offered`);
}
// A stamp the board can't vouch for (t null after a move) never reads as waiting to meet.
c.LV={duel:[{id:'tu',to:0,s:'active',n:1,t:null,turn:false,shots:[],incoming:[[1,0,0]],record:[0,0]}]};
vm.runInContext('duScreen(0)',c);
assert.doesNotMatch(elements.v.innerHTML,/Waiting for your ships to meet|Arrived/,'move with an unknown time shows no age');
console.log('duel Resign: hidden in reveal, withdraw before joining PASS');

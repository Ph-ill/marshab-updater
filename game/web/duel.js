// Asteroid duel. Existing page primitives, portraits and live-state polling only.
let DU_TO=null,DU_POS=null,DU_SHIP=0,DU_CELL=null,DU_ERR="",DU_BUSY=false;
let DU_KEY=null;
const DU_PLACEMENTS=new Map();
const DU_OPEN=["draft","wait","invited","active","reveal"];
function duGames(){return LV?.duel||[]}
function duGame(to){return duGames().find(g=>g.to===to)}
function duStatus(g){
  const name=nm(g.to);
  if(g.s==="draft")return "Hide your fleet";
  if(g.s==="invited")return name+" invited you";
  if(g.s==="wait")return "Waiting for "+name+" to join";
  if(g.s==="reveal")return "Checking both fields";
  if(g.s==="cheat")return name+"'s answers didn't match the field";
  if(g.s==="done")return g.why===2?(g.win?name+" resigned":"You resigned"):g.win?"You sank "+name+"'s fleet in "+g.shots.length+" shots":name+" sank your fleet";
  if(g.s==="version")return name+"'s ship needs the duel update";
  if(g.s==="busy")return name+" already has three duels open";
  if(g.s==="declined")return "Invitation declined";
  if(g.s==="called")return "Duel put away";
  if(g.p!=null)return "Your shot's on its way";
  return g.turn?"Your turn":name+"'s turn";
}
function duHome(){
  if(!LV?.on||!Array.isArray(LV.duel))return "";
  const games=duGames();
  return `<section id=du-home><div class=lab><span>Asteroid duel</span><span>${games.some(g=>g.turn)?"your move":"ship to ship"}</span></div>${games.length?games.map(g=>`<button class=row data-go=duel/${g.to}><span class=pt>${portrait(g.to)}</span><span class=t><b>${h(nm(g.to))}</b><small>${h(duStatus(g))}</small></span></button>`).join(""):`<p class=dim>Hide six cells of ships in an asteroid field. Take turns firing when your ships meet.</p>`}<button class="btn sec" data-go=duel><span>Start a duel</span></button></section>`;
}
function duCells(pos){return (pos||[]).map((p,i)=>p?Array.from({length:3-i},(_,k)=>p[0]+k*(p[1]?6:1)):[])}
function duLegal(pos){
  if(!pos||pos.some(p=>!p))return false;
  const all=duCells(pos),used=[];
  for(let i=0;i<3;i++){
    const [c,d]=pos[i],len=3-i;
    if(c<0||c>=36||(d?Math.floor(c/6)+len>6:c%6+len>6))return false;
    for(const a of all[i])for(const b of used)if(a===b||Math.abs(Math.floor(a/6)-Math.floor(b/6))+Math.abs(a%6-b%6)===1)return false;
    used.push(...all[i]);
  }
  return true;
}
function duShuffle(){
  for(let k=0;k<10000;k++){
    const p=[3,2,1].map(()=>[Math.random()*36|0,Math.random()*2|0]);
    if(duLegal(p)){DU_POS=p;return}
  }
  DU_POS=[[0,0],[12,0],[35,0]];
}
function duCoord(c){return "ABCDEF"[c%6]+(Math.floor(c/6)+1)}
function duGrid(ships,shots,mode,selected=null,pending=null){
  const cells=(ships||[]).flat(),hits=shots.filter(z=>z[2]>0).map(z=>z[1]);
  // A sink reveals the connected hit run containing its last cell (edge adjacency).
  const sunk=new Set();
  for(const z of shots)if((z[2]&7)>=2){
    const q=[z[1]];while(q.length){const c=q.pop();if(sunk.has(c))continue;sunk.add(c);for(const p of hits)if(!sunk.has(p)&&Math.abs(c%6-p%6)+Math.abs(Math.floor(c/6)-Math.floor(p/6))===1)q.push(p)}
  }
  let o=`<div class="du-grid ${mode==="small"?"du-small":""}" role=group aria-label="${mode==="place"?"Hide your fleet":mode==="fire"?"Opponent field":"Your field"}"><span></span>`;
  for(const col of "ABCDEF")o+=`<span class=du-axis>${col}</span>`;
  for(let c=0;c<36;c++){
    if(c%6===0)o+=`<span class=du-axis>${Math.floor(c/6)+1}</span>`;
    const shot=shots.find(z=>z[1]===c),state=shot?(shot[2]?"hit":"miss"):cells.includes(c)?"ship":"",active=mode==="place"||mode==="fire"&&!shot;
    o+=`<button class="du-cell ${state}${sunk.has(c)?" sunk":""}${selected===c?" selected":""}" aria-label="${duCoord(c)}${state?", "+state:""}${pending===c?", on its way":""}" ${active?`data-du${mode==="place"?"place":"cell"}=${c}`:"disabled"} aria-pressed="${selected===c}">${shot?(shot[2]?"×":"·"):pending===c?"?":""}</button>`;
  }
  return o+`</div>`;
}
// Keep the action-only dock used by Hail, with an always-enabled way home.
function duDock(action=""){
  dock(`<div class=tnav><button class="btn sec" data-go=home><span>Home</span></button>${action}</div>`,"");
}
function duScreen(to){
  shipTop();
  const g=duGame(to);
  const key=g?to+":"+g.id:null;
  if(to!=null&&(DU_TO!==to||DU_KEY!==key)){
    if(DU_KEY)DU_PLACEMENTS.set(DU_KEY,DU_POS);
    DU_TO=to;DU_KEY=key;DU_POS=DU_PLACEMENTS.get(key)||[null,null,null];DU_SHIP=0;DU_CELL=null;DU_ERR="";
  }
  let o=`<div class=kick><div class=lab>Asteroid duel</div><h1>${to==null?"Pick a crewmate":g&&(g.s==="draft"||g.s==="invited")?"Hide your fleet":h(nm(to))}</h1></div>`;
  if(!LV){o+=`<p class=dim role=status>Asking your ship.</p>`;$("v").innerHTML=o;duDock();return}
  if(to==null){
    o+=`<section><div class=lab>One duel with each crewmate</div>`;
    for(let c=0;c<N;c++)if(c!==S.here&&S.cond[c]!==2){
      const p=lvPeer(c),old=lvOld(p),off=lvOff(p),existing=duGame(c);
      o+=`<button class=row ${existing?`data-go=duel/${c}`:`data-dunew=${c}`} ${old||off||DU_BUSY?"disabled":""}><span class=pt>${portrait(c)}</span><span class=t>${h(nm(c))}<small>${old?"Needs the ship software update":off?"Ship-to-ship is off":existing?h(duStatus(existing)):lvNear(c)}</small></span></button>`;
    }
    o+=`</section>`;duDock();
  }else if(!g){o+=`<p class=dim>No duel is open with ${h(nm(to))}.</p>`;duDock(`<button class="btn sec" data-go=duel><span>Pick a crewmate</span></button>`)}
  else if(g.s==="draft"||g.s==="invited"){
    o+=`<p class=dim>Place your 3-cell, 2-cell and 1-cell ships. Keep an empty cell between ship edges. Tap a ship, then a cell. Tap the same cell to turn.</p><section><div class=lab><span>Your field</span><span>${h(nm(to))}</span></div><div class=du-tools>${[3,2,1].map((n,i)=>`<button class="btn sec" data-duship=${i} aria-pressed="${DU_SHIP===i}">${n} cell${n===1?"":"s"}</button>`).join("")}</div>${duGrid(duCells(DU_POS),[],"place")}<div class=du-tools><button class="btn sec" data-duturn=1>Turn</button><button class="btn sec" data-dushuffle=1>Shuffle</button></div><p class=fine>${duLegal(DU_POS)?"Your field is ready. Locking keeps it fixed for this duel.":"Place all three ships without overlap or touching edges."}</p></section>`;
    if(g.s==="invited")o+=`<button class="btn sec" data-duact=decline><span>Decline invitation</span></button>`;
    else o+=`<button class="btn sec" data-duact=discard ${DU_BUSY?"disabled":""}><span>Discard your draft</span></button>`;
    duDock(`<button class="btn pri" data-duact=${g.s==="invited"?"accept":"invite"} ${duLegal(DU_POS)&&!DU_BUSY?"":"disabled"}><span>Lock in and ${g.s==="invited"?"join":"invite"}</span></button>`);
  }else{
    const ended=!DU_OPEN.includes(g.s),can=g.turn&&!g.pending&&!DU_BUSY;
    const field=ended?g.their:null;
    o+=`<p class=dim role=status>${h(duStatus(g))}</p>${g.update?`<p class=fine>${h(nm(to))}'s ship may need 0.3.1.</p>`:""}${g.nl?`<p class=fine>${h(nm(to))}'s light is off. Your move waits on ${h(nm(to))}'s page.</p>`:""}<section><div class=lab><span>${h(nm(to))}'s field</span><span>${ended?"revealed":"your shots"}</span></div>${duGrid(field,g.shots,can?"fire":"view",DU_CELL,g.p)}<p class=fine>${g.pending||g.p!=null?"On its way":g.t?"Arrived "+lvAgo(g.t*1000):"Waiting for your ships to meet"}</p></section><section><div class=lab><span>Your field</span><span>${g.incoming.length} shots received</span></div>${duGrid(g.layout,g.incoming,"small")}</section>`;
    if(ended){o+=`<p class=dim>${g.record[0]}-${g.record[1]} between you and ${h(nm(to))}.</p>`;duDock(`<button class="btn sec" data-dunew=${to}><span>Rematch</span></button>`)}
    else{
      o+=`<section><button class="btn sec" data-duact=resign><span>Resign</span></button><button class="btn sec" data-duact=call><span>Call it</span><i>after 3 days</i></button></section>`;
      duDock(`<button class="btn pri" data-duact=fire ${can&&DU_CELL!=null?"":"disabled"}><span>${DU_CELL!=null?"Fire at "+duCoord(DU_CELL):"Pick a cell"}</span></button>`);
    }
  }
  $("v").innerHTML=o+`<p class=err id=du-error role=alert>${h(DU_ERR)}</p>`;
}
const home_du=home;home=function(){home_du();const k=document.querySelector("#v>.kick");if(k)k.insertAdjacentHTML("afterend",duHome())};
const lvPaint_du=lvPaint;lvPaint=function(){if(route.split("/")[0]==="duel")return view();return lvPaint_du()};
const view_du=view;view=function(){const [a,b]=route.split("/");if(tok&&S&&a==="duel"){if(!LV)lvLoad();return duScreen(b==null?null:+b)}return view_du()};
document.addEventListener("click",async ev=>{
  const t=ev.target.closest("[data-dunew],[data-duship],[data-duplace],[data-duturn],[data-dushuffle],[data-ducell],[data-duact]");if(!t||t.disabled||DU_BUSY)return;
  const d=t.dataset;
  if(d.duship!=null){DU_SHIP=+d.duship;return view()}
  if(d.dushuffle!=null){duShuffle();DU_ERR="";return view()}
  if(d.duturn!=null){if(DU_POS[DU_SHIP])DU_POS[DU_SHIP][1]^=1;return view()}
  if(d.duplace!=null){const c=+d.duplace,p=DU_POS[DU_SHIP];DU_POS[DU_SHIP]=[c,p?.[0]===c?p[1]^1:p?.[1]||0];return view()}
  if(d.ducell!=null){DU_CELL=+d.ducell;return view()}
  const action=d.dunew!=null?"new":d.duact,to=d.dunew!=null?+d.dunew:DU_TO;
  if((action==="resign"||action==="call")&&!confirm(action==="resign"?"Resign this duel? This counts as a loss.":"Put this duel away without a result?"))return;
  DU_BUSY=true;DU_ERR="";view();
  try{await api("/api/live/duel",{action,to,layout:DU_POS,cell:DU_CELL});DU_CELL=null;if(["lock","invite","accept","discard"].includes(action)){DU_PLACEMENTS.delete(DU_KEY);DU_KEY=null;DU_POS=null}await lvLoad();if(action==="new"){DU_TO=null;go("duel/"+to)}if(action==="discard")go("duel")}
  catch(e){DU_ERR=e.message||"Your move did not go. Try again."}
  finally{DU_BUSY=false;view()}
});

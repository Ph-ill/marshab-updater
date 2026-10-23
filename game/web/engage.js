// The Long Voyage: engagement screens. Inlined into app.html by build.py (/*ENGAGE_JS*/)
// and uses its helpers (S, T, R, h, nm, pad, ship, go, view, api, dock, shipTop, story,
// portrait, meter, openRow). The words come from /engage.json (tools/lve.py); if that
// file is missing the page simply has no engagement parts.
//
// Waiting keys from the ship (lv/engage.py): kind * 65536 + detail.
const W={DROP:1,JOB:2,GIFT:3,VOTE:4,DIL:5,HOOK:6,RES:7};
let EG=null,NEWS=new Set(),gd={mode:0,to:null,item:null};
const wk=(k,d)=>k*65536+d;
const hhmm=(m)=>pad(Math.floor(m/60))+":"+pad(m%60);
const A=(s)=>R.fill(s,S.you);
function engLoad(){return fetch("/engage.json").then((r)=>r.ok?r.json():null).then((j)=>{EG=j}).catch(()=>{})}
function engSeen(){if(S&&S.eng)for(const k of S.eng.new)NEWS.add(k)}
const isNew=(k)=>NEWS.has(k);
const tag=(k,t)=>isNew(k)?`<span class=new>New</span>`:`<span>${t}</span>`;

// ---- raw story ------------------------------------------------------------------------
let RAW=null,RAWsrc="";
function raw(){if(RAWsrc!==S.story){RAWsrc=S.story;RAW=Uint8Array.from(atob(S.story),(c)=>c.charCodeAt(0))}return RAW}
function entries(f){const b=raw(),out=[];for(let i=0;i+8<=b.length;i+=8){const e=Array.from(b.slice(i,i+8));if(f(e))out.push(e)}return out}
function line(e){const r=new Renderer(T,EG);return(r.entry(e)||"").trim()}

// ---- cliffhanger: "Tonight" on the day it lands, "Last night" the morning after --------
function hookCard(c){return c!==NONE&&T.cards[c]&&T.cards[c].h}
function hookBlock(){
  const ev=(e)=>(e[1]===O.EVENT||e[1]===O.DEC_OPEN||e[1]===O.RES_OPEN)&&hookCard(e[2]);
  const tn=entries((e)=>e[0]===S.day&&ev(e)).pop();
  if(tn)return `<div class=hook><div class="lab r"><span>Tonight</span><span>FD ${pad(S.day)}</span></div><div class=body><p class=lead>${h(line(tn))}</p><p class=dim style="font-size:15px">The log picks this up tomorrow.</p></div></div>`;
  const ln=entries((e)=>e[0]===S.day-1&&ev(e)).pop();
  if(!ln)return"";
  const res=entries((e)=>e[0]===S.day&&EG&&EG.res&&EG.res[e[2]]===ln[2]&&e[1]===O.EVENT)[0];
  return `<div class=hook><div class=lab><span>Last night</span><span>FD ${pad(S.day-1)}</span></div><div class=body><p class=lead>${h(line(ln))}</p><div class=then><div class="lab r">This morning</div><p>${res?h(line(res)):"No word yet. The fleet is still listening."}</p></div></div></div>`;
}

// ---- found things ---------------------------------------------------------------------
function dropOf(x){return EG.drops[x[1]][x[2]]}
function found(){
  const got=new Set();
  for(const x of S.eng.drops)if(x[3]){const d=dropOf(x);if(d.art)got.add(d.art)}
  for(const j of S.eng.jobs)if(j[3]>=0){const o=EG.jobs[j[1]].out[j[3]];if(o.art)got.add(o.art)}
  return got;
}
function storyPct(){
  // Endings don't count. The shipped text.json has no card ids; endings are the cards
  // with a title ("ti"), which tests/test_engage.py holds lvc to.
  const seen=new Set(),tot=T.cards.filter((c)=>!c.ti).length;
  for(const e of entries((e)=>[O.EVENT,O.DEC_OPEN,O.DIL_OPEN,O.RES_OPEN].includes(e[1])))seen.add(e[2]);
  return Math.min(100,Math.floor(100*seen.size/Math.max(1,tot)));
}
function hooksSeen(){return entries((e)=>e[1]===O.EVENT&&hookCard(e[2])).length}
function patchGot(p){
  const [r,n]=p.r,E=S.eng;
  const v={day:S.day,votes:E.stats.votes,rescues:E.stats.rescues,gifts:E.stats.gifts,hooks:hooksSeen(),
    opened:E.drops.filter((x)=>x[3]).length,artifacts:found().size,story:storyPct(),streak:E.streak.best}[r];
  return v>=n;
}

// ---- home: the cliffhanger, then everything waiting, then the watch line -------------
function engTop(){
  if(!EG||!S.eng)return S.open.length?`<section><div class=lab><span>Needs you</span><span>${S.open.length}</span></div>${S.open.map(openRow).join("")}</section>`:allClear();
  const E=S.eng,rows=[];
  const dr=E.drops[E.drops.length-1];
  if(dr&&!dr[3])rows.push(`<button class=go data-go="drop/${dr[0]}"><span class=lab><span>Daily drop</span>${tag(wk(W.DROP,dr[0]),EG.tiers[dr[1]])}</span><b>Something came up with the cargo. Sealed.</b></button>`);
  const jb=E.jobs.find((j)=>j[0]===S.day);
  if(jb){const J=EG.jobs[jb[1]];rows.push(`<button class=go data-go="job/${jb[0]}"><span class=lab><span>Timed job · ${h(J.l)}</span>${jb[3]>=0?tag(wk(W.JOB,S.day),"Done"):`<span>${E.minute!=null?"About "+hhmm(jb[2]):"Later today"}</span>`}</span><b>${h(first(A(J.t)))}</b></button>`)}
  for(const a of E.gifts.asks)rows.push(`<button class=go data-go="gifts"><span class=lab><span>Ask from ${h(nm(a[1]))}</span>${tag(wk(W.GIFT,(a[0]*8+a[1])*4+a[3]),"Open")}</span><b>${h(nm(a[1]))} asks for ${h(EG.gifts.items[a[2]][0])}.</b></button>`);
  const inn=E.gifts.in.filter((g)=>g[3]!==1&&g[0]>=S.day-1);
  if(inn.length)rows.push(`<button class=go data-go="gifts"><span class=lab><span>Cargo in</span>${tag(wk(W.GIFT,(inn[0][0]*8+inn[0][1])*4+inn[0][3]),"FD "+pad(inn[0][0]))}</span><b>${inn.map((g)=>`${h(nm(g[1]))} sent ${h(EG.gifts.items[g[2]][0])}.`).join(" ")}</b></button>`);
  let o=hookBlock();
  const n=rows.length+S.open.length;
  o+=n?`<section><div class=lab><span>Needs you</span><span>${n}</span></div>${rows.join("")}${S.open.map(openRow).join("")}</section>`:allClear();
  const s=E.streak;
  o+=`<section style="padding-top:16px"><button class=wline data-go="streak"><span>Watch duty</span><span><b>${s.cur}</b> ${s.cur===1?"day":"days"}${s.today?" · logged today":""}</span></button>${E.gifts.gave?"":`<button class=wline data-go="gifts"><span>Cargo run</span><span>send a crewmate something</span></button>`}</section>`;
  return o;
}

// Nothing waiting is a state too: say so, rather than leave a gap where the list was.
function allClear(){return `<section><div class=lab><span>Needs you</span><span>0</span></div><p class=empty><b>All clear</b><span>Nothing needs an answer today. The voyage carries on.</span></p></section>`}

// ---- drop -----------------------------------------------------------------------------
function dropScreen(d){
  const x=S.eng.drops.find((y)=>y[0]===d);if(!x)return go("home");
  shipTop();
  const it=dropOf(x),rare=x[1]===EG.tiers.length-1;
  let o=`<div class=kick><div class=lab>Daily drop · FD ${pad(d)}</div><h2>${x[3]?h(it.k):"For "+h(nm(S.you))}</h2></div>`;
  if(!x[3])o+=`<div class=seal><span class="lab ${rare?"r":""}">${h(EG.tiers[x[1]])}</span><b>Sealed</b><p class=dim style="font-size:15px">One item a flight day. It keeps until you open it.</p></div>`;
  else{
    o+=`<div class=card><div class="lab ${rare?"r":""}"><span>${h(EG.tiers[x[1]])}</span><span>FD ${pad(d)}</span></div><div class=body><p class=lead>${h(A(it.t))}</p></div></div>`;
    if(it.art){const a=EG.arts.find((z)=>z.id===it.art);o+=`<p class=note>Added to your file: <b style="color:var(--ink)">${h(a.n)}</b>. ${h(a.t)}</p>`}
  }
  $("v").innerHTML=o;
  dock(x[3]?`<button class="btn sec" data-go="home"><span>Back aboard</span><i>←</i></button>`:`<button class="btn pri" data-eng="open:${d}"><span>Open it</span><i>${h(EG.tiers[x[1]])}</i></button>`,"home");
}

// ---- timed job ------------------------------------------------------------------------
function jobScreen(d){
  const j=S.eng.jobs.find((y)=>y[0]===d);if(!j)return go("home");
  shipTop();
  const J=EG.jobs[j[1]];
  let o=`<div class=kick><div class=lab>Timed job · FD ${pad(d)}</div><h2>${h(J.l)}</h2></div><div class=card><div class=lab><span>${h(nm(S.you))}</span><span>${j[3]>=0?"Done":S.eng.minute!=null?"About "+hhmm(j[2]):"Later today"}</span></div><div class=body><p class=lead>${h(A(J.t))}</p>`;
  if(j[3]>=0){const r=J.out[j[3]];o+=`<div class=then style="border-top:1px solid var(--rule);margin-top:12px;padding-top:8px"><div class="lab r">Result</div><p>${h(A(r.t))}</p></div>`;
    if(r.art){const a=EG.arts.find((z)=>z.id===r.art);o+=`<p class=dim style="font-size:15px">Added to your file: ${h(a.n)}.</p>`}}
  else o+=`<p class=dim style="font-size:16px">${S.eng.minute!=null?`Should wrap up about ${hhmm(j[2])}, your time. Check back after.`:"Should wrap up later today."}</p>`;
  $("v").innerHTML=o+`</div></div>`;
  dock(`<button class="btn sec" data-go="home"><span>Back aboard</span><i>←</i></button>`,"home");
}

// ---- gifts ----------------------------------------------------------------------------
function giftsScreen(){
  shipTop();
  const E=S.eng.gifts,G=EG.gifts,mates=[...Array(N).keys()].filter((j)=>j!==S.you&&S.cond[j]!==2);
  let o=`<div class=kick><div class=lab>Cargo transfer</div><h2>Gifts and asks</h2><p class=dim style="font-size:16px">One gift and one ask a flight day. An ask nobody can answer just lapses after ${G.ask_days} days.</p></div>`;
  if(E.asks.length)o+=`<section><div class=lab><span>Asked of you</span><span>${E.asks.length}</span></div>${E.asks.map((a)=>`<div class=row><span class=pt>${portrait(a[1])}</span><span class=t>${h(nm(a[1]))} asks for ${h(G.items[a[2]][0])}<small>FD ${pad(a[0])} · open to FD ${pad(a[0]+G.ask_days-1)}</small></span><button class="btn sec" style="width:auto" data-eng="ans:${a[1]}:${a[2]}">Send</button></div>`).join("")}</section>`;
  const mode=gd.mode,can=mode?!E.asked:!E.gave;
  o+=`<section><div class=lab><span>Send</span><span>${can?"1 today":"done today"}</span></div><div class=grid2><button class=opt data-eng="mode:0" aria-pressed="${mode===0}"><span class=k>G</span><span class=t>Give</span></button><button class=opt data-eng="mode:1" aria-pressed="${mode===1}"><span class=k>A</span><span class=t>Ask</span></button></div>`;
  if(can){
    o+=`<div class=lab style="margin-top:16px">${mode?"Ask whom":"To whom"}</div><div class=grid2>${mates.map((j)=>`<button class=opt data-eng="to:${j}" aria-pressed="${gd.to===j}"><span class=k>${pad(j+1)}</span><span class=t>${h(nm(j))}</span></button>`).join("")}</div>`;
    o+=`<div class=lab style="margin-top:16px">${mode?"For":"What"}</div><div class=items>${G.items.map((x,i)=>x[mode?2:1]?`<button class=opt data-eng="item:${i}" aria-pressed="${gd.item===i}"><span class=k>${pad(i+1)}</span><span class=t><b>${h(x[0])}</b></span></button>`:"").join("")}</div>`;
  }else o+=`<p class=dim style="margin-top:8px">${mode?"Your ask for today is on its way.":"Today's gift is on the cargo run."} Tomorrow there's room for another.</p>`;
  o+=`</section>`;
  const hist=[...E.in.map((g)=>[g[0],1,g]),...E.out.map((g)=>[g[0],0,g])].sort((a,b)=>b[0]-a[0]).slice(0,10);
  if(hist.length)o+=`<section><div class=lab><span>Recent</span></div><ul class=log>${hist.map(([d,inn,g])=>`<li class="${inn?"big":"you"}"><span class="m dim" style="font-size:14px">FD ${pad(d)}</span><br>${h(R.fill(G.sys[["give","ask","answer"][g[3]]],inn?g[1]:S.you,NONE,{T:inn?nm(S.you):nm(g[1]),item:G.items[g[2]][0]}))}</li>`).join("")}</ul></section>`;
  $("v").innerHTML=o;
  const ok=can&&gd.to!=null&&gd.item!=null;
  dock(can?`<button class="btn pri" data-eng="send"${ok?"":" disabled"}><span>${mode?"Send ask":"Send gift"}</span><i>${ok?h(nm(gd.to)):"choose"}</i></button>`:`<button class="btn sec" data-go="home"><span>Back aboard</span><i>←</i></button>`,"home");
}

// ---- watch duty -----------------------------------------------------------------------
function streakScreen(){
  shipTop();
  const s=S.eng.streak,days=new Set(s.days),cov=new Set(s.covered),A1=nm(S.you);
  let o=`<div class=kick><div class=lab>Watch duty · ${h(ship(S.you))}</div><h1 class=m>${s.cur} <span class=dim style="font-weight:400;font-size:21px">${s.cur===1?"day":"days"}</span></h1><p class=dim>Best ${s.best}. Any tap on a flight day counts as a watch. Miss a day and ${h(A1)} covers it, up to twice a flight week.</p>`;
  const last=s.cur===0&&S.day>1&&s.best>0;
  if(last)o+=`<p>A new watch starts with your next tap.</p>`;
  o+=`</div><section><div class=lab><span>Flight days</span><span>FD 01–${pad(S.season)}</span></div><div class=watch>`;
  for(let w=0;w<Math.ceil(S.season/7);w++){
    o+=`<span>W${w+1}</span>`;
    for(let i=1;i<=7;i++){const d=w*7+i;const c=d>S.day?"":days.has(d)?"w":cov.has(d)?"c":"";o+=`<i class="${c}${d===S.day?" t":""}">${d<=S.day?d:""}</i>`}
  }
  o+=`</div><div class=key><span><i style="background:var(--ink)"></i>Your watch</span><span><i style="border-style:dashed"></i>${h(A1)} covered</span><span><i style="border:2px solid var(--rust)"></i>Today</span></div></section>`;
  o+=`<section><div class=lab><span>Badges</span><span>${EG.badges.filter((b)=>s.best>=b[0]).length}/${EG.badges.length}</span></div>${EG.badges.map(([n,t])=>`<div class=row><span class="pt m" style="display:flex;align-items:center;justify-content:center;font-weight:700;${s.best>=n?"background:var(--ink);color:var(--paper)":"border-color:var(--rule);color:var(--graph)"}">${n}</span><span class=t>${h(t)}<small>${s.best>=n?"Earned":n+" days in a row"}</small></span></div>`).join("")}</section>`;
  $("v").innerHTML=o;
  dock(`<button class="btn sec" data-go="file"><span>Crew file</span><i>→</i></button>`,"file");
}

// ---- crew file: patches, artifacts, what you know about each crewmate ------------------
function patchArt(p,on){
  const k=hash(p.id),s=["M20 3L37 20L20 37L3 20Z","M20 3A17 17 0 1 1 19.9 3Z","M6 5H34V24L20 37L6 24Z","M20 3L36 33H4Z"][k%4];
  const ink=on?"var(--ink)":"var(--rule)";
  return `<svg viewBox="0 0 40 40" aria-hidden="true"><path d="${s}" fill="none" stroke="${ink}" stroke-width="1.5"/><text x="20" y="${k%4===3?28:24}" text-anchor="middle" font-family="ui-monospace,Menlo,monospace" font-size="9" font-weight="700" fill="${on?"var(--rust)":ink}">${h(p.id.slice(0,4).toUpperCase())}</text></svg>`;
}
function fileScreen(){
  shipTop();
  const E=S.eng,pct=storyPct(),got=found(),Y=S.you;
  let o=`<div class=kick><div class=lab>Crew file · ${h(ship(Y))}</div><div class=pct>${pct}%</div><p class=dim style="margin-top:0">of this voyage's story discovered</p><div class=gauge style="padding-top:0">${meter(pct)}</div></div>`;
  const P=EG.patches.map((p)=>[p,patchGot(p)]);
  o+=`<section><div class=lab><span>Mission patches</span><span>${P.filter((x)=>x[1]).length}/${P.length}</span></div><div class=patches>${P.map(([p,on])=>`<div class="patch ${on?"":"no"}">${patchArt(p,on)}<div><b>${h(p.n)}</b><small>${h(on?p.t:p.l||"Not yet")}</small></div></div>`).join("")}</div></section>`;
  o+=`<section><div class=lab><span>Artifacts</span><span>${got.size}/${EG.arts.length}</span></div>${EG.arts.map((a)=>`<div class=row><span class=t>${got.has(a.id)?h(a.n):"<span class=dim>Unknown item</span>"}<small>${got.has(a.id)?h(a.t):"Turns up in a drop or on a job."}</small></span></div>`).join("")}</section>`;
  const met=new Set(),shared=new Set(),traded=new Set();
  for(const e of entries(()=>true)){
    const c=e[1],a=e[3],b=c===O.ACT?(e[4]===0?e[5]:NONE):c===O.NOTE||c===O.GIFT?e[5]:e[4];
    if([O.EVENT,O.DEC_OPEN,O.DIL_OPEN,O.RES_OPEN,O.ACT,O.NOTE,O.GIFT,O.MOVE].includes(c)){if(a<N)met.add(a);if(b<N&&c!==O.MOVE)met.add(b)}
    if(c!==O.MOVE&&c!==O.DIL_OPEN&&(a===Y&&b<N||b===Y&&a<N)){const j=a===Y?b:a;if(j!==Y){shared.add(j);if(c===O.GIFT)traded.add(j)}}
  }
  const F=EG.file;
  o+=`<section><div class=lab><span>Crewmates</span><span>${[...Array(N).keys()].filter((j)=>j!==Y&&met.has(j)).length}/${N-1} met</span></div>`;
  for(let j=0;j<N;j++){if(j===Y)continue;
    const t=S.traits[j];let ax=0;for(let i=1;i<3;i++)if(Math.abs(t[i])>Math.abs(t[ax]))ax=i;
    const lean=F.lean[ax][t[ax]>=0?0:1];
    o+=`<div class=cf><span class=pt>${portrait(j)}</span><div><b>${h(nm(j))}</b>`;
    o+=met.has(j)?`<p>${h(R.fill(F.met,NONE,NONE,{T:nm(j),S:ship(j)}))}</p>`:`<p class=no>Not in your log yet.</p>`;
    o+=shared.has(j)?`<p>${h(R.fill(F.shared,NONE,NONE,{lean}))}</p>`:`<p class=no>Hasn't shared a shift with ${h(nm(Y))}.</p>`;
    o+=traded.has(j)?`<p>${h(F.traded[j%F.traded.length])}</p>`:`<p class=no>Swap cargo to learn more.</p>`;
    o+=`</div></div>`;
  }
  o+=`</section>`;
  const un=E.drops.filter((x)=>!x[3]);
  o+=`<section><div class=lab><span>Drops</span><span>${E.drops.length-un.length}/${E.drops.length} opened</span></div>${E.drops.slice().reverse().map((x)=>`<button class=row data-go="drop/${x[0]}"><span class="m dim" style="width:48px">FD ${pad(x[0])}</span><span class=t>${x[3]?h(dropOf(x).k):"Sealed"}<small>${h(EG.tiers[x[1]])}</small></span></button>`).join("")}</section>`;
  $("v").innerHTML=o;
  dock(`<button class="btn sec" data-go="gifts"><span>Gifts and asks</span><i>cargo</i></button>`,"file");
}

const ENG={drop:(b)=>dropScreen(+b),job:(b)=>jobScreen(+b),gifts:giftsScreen,streak:streakScreen,file:fileScreen};

async function engClick(el,v){
  const [k,a,b]=v.split(":");
  if(k==="mode"){gd={mode:+a,to:gd.to,item:null};return view()}
  if(k==="to"){gd.to=+a;return view()}
  if(k==="item"){gd.item=+a;return view()}
  el.disabled=true;
  try{
    if(k==="open"){await api("/api/open",{day:+a});await refresh();return go("drop/"+a)}
    if(k==="send"){await api("/api/gift",{item:gd.item,to:gd.to,mode:gd.mode});gd={mode:gd.mode,to:null,item:null};await refresh();return view()}
    if(k==="ans"){await api("/api/gift",{item:+b,to:+a,mode:2});await refresh();return view()}
  }catch(e){el.disabled=false;const d=$("dock");d.querySelector(".off")?.remove();d.insertAdjacentHTML("afterbegin",`<div class=off role=alert>${h(e.message)}</div>`)}
}

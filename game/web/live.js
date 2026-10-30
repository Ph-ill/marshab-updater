// Ship-to-ship (board/lvlive.py, lvliveapi.py; GET/POST /api/live*): Hail, and the Settings
// switches and radio check. A hail is a few words sent to a crewmate's own ship over
// Bluetooth: their ship's light flashes for a few seconds and the hail waits on
// their home screen; you see "Sending", "Will deliver" (their ship is out of range: yours
// keeps trying while they're about), "Delivered", then "<name> saw it" once they open the
// game. Hail back within 10 minutes. One on its way per crewmate, one every 2 minutes to
// the same one, 20 a day. Each player stays on their own ship's Wi-Fi; only ships talk.
// Hooked onto app.html's home/crew/setScreen/view/pollV from here, loaded after settings.js.
const LV_PH=["Hello from my ship","Good morning","Coffee?","Lunch?","Come take a look","Nice work","Need a hand?","Heading out"];
let LV=null,LVV=-1,LVK=0,LVT=null,LVP=null,LVB=0,LVE="",LVS=0;   // state, its version, fast-poll timer; the hail form: to, phrase, back, error, sending
async function lvLoad(){
  let j;
  try{j=await api("/api/live")}catch(e){if(e.status===404||e.status===401)LV=null;return}
  // A ship (or a mock) without ship-to-ship answers something else: no hail card at all.
  LV=j&&Array.isArray(j.out)&&Array.isArray(j.in)&&Array.isArray(j.peers)?j:null;
  if(!LV)return;
  LVV=LV.lv;
  const fast=LV.out.some((o)=>o.st===0);
  clearTimeout(LVK);if(fast)LVK=setTimeout(lvLoad,1000);
  lvPaint();
}
function lvPaint(){
  const a=route.split("/")[0];
  if(a==="home"||a==="hail"||a==="coex"||(a==="crew"&&route.includes("/")))return view();
  const d=$("set-live");if(d)d.outerHTML=lvSect();
}
function lvAgo(t){if(!t)return "earlier";const s=Math.max(0,(Date.now()-t)/1000|0);return s<60?"just now":s<3600?Math.round(s/60)+" min ago":Math.round(s/3600)+" h ago"}
function lvPeer(j){return LV&&LV.peers.find((p)=>p.s===j)}
function lvNear(j){const p=lvPeer(j);if(!p||p.ago==null)return "Not in range lately";if(p.ago<=180)return "<b class=near>Nearby</b>";const s=p.ago;return "In range "+(s<3600?Math.round(s/60)+" min":Math.round(s/3600)+" h")+" ago"}
function lvSt(o){return ["Sending\u2026","Will deliver · when your ships meet","Delivered",h(nm(o.to))+" saw it","Didn't go · ships never met"][o.st]}
function lvOnWay(j){return LV&&LV.out.some((o)=>o.to===j&&o.st<2)}
// a crewmate's ship: "old" (heard without Hail: needs the update), "off" (has Hail, paused),
// "nl" (its hail light is switched off: a hail lands there as a note only)
function lvOld(p){return !!p&&p.cap===0&&!p.off}
function lvOff(p){return !!p&&p.cap===0&&!!p.off}
function lvNl(p){return !!p&&!!p.nl}
// Paused after a problem (lvlivex.py's fault reasons): turning it back on is up to you.
// For the other reasons a tap can't help, so the words say what will.
function lvFault(){return !!LV&&(LV.why==="restarted after a fault"||(LV.why||"").startsWith("fault"))}
function lvPausedWhy(){
  const w=LV.why||"";
  if(w==="paused for the fleet"||w==="core changed")return "Hails are paused on every ship for now. Your ship still syncs the story with the fleet, and an update will bring hails back.";
  if(w==="no Bluetooth")return "Hails need your ship's Bluetooth, and it isn't running, so the story isn't syncing with other ships either. Restarting your ship may bring it back.";
  if(w==="no fleet key")return "Your ship isn't set up for the fleet yet, so it can't swap hails or the story with other ships.";
  if(w.startsWith("didn't start"))return "Hails didn't start on your ship this time. They'll try again the next time it restarts. Your ship still syncs the story with the fleet.";
  return `Hails paused on their own ${h(lvWhy())}. Your ship still syncs the story with the fleet.`;
}
// Hail paused on your ship: a calm line on Home instead of the card vanishing; turned off
// in Settings: nothing on Home
function lvPausedCard(){
  if(!LV||LV.on||!LV.why||LV.why==="turned off")return "";
  return `<section id=lv-home><div class=lab><span>Hails</span><span>paused</span></div><p class=dim>${lvPausedWhy()}</p>${lvFault()?`<button class="btn sec" data-lvset=on><span>Turn hails back on</span></button>`:""}</section>`;
}
function lvHomeCard(){
  if(LV&&!LV.on)return lvPausedCard();
  if(!LV)return "";
  const inn=LV.in.slice().reverse(),out=LV.out.slice().reverse().slice(0,4);
  let o=`<section id=lv-home><div class=lab><span>Hails</span><span>${inn.length?inn.length+" today":"ship to ship"}</span></div>`;
  for(const x of inn.slice(0,4))o+=`<div class="row lvin${x.seen?"":" nw"}"><span class=pt>${portrait(x.by)}</span><span class=t><b>${h(nm(x.by))}${x.back?" hailed you back":""}</b><small class=lvq>\u201c${h(LV_PH[x.ph])}\u201d</small><small>${h(ship(x.from))} · ${lvAgo(x.t)}</small></span>${x.can&&!x.back?`<button class="btn sec lvbk" data-lvbk=${x.from}><span>Hail back</span></button>`:""}</div>`;
  for(const x of out)o+=`<div class="row lvout"><span class=t>To ${h(nm(x.to))} · \u201c${h(LV_PH[x.ph])}\u201d<small class="lvs s${x.st}">${lvSt(x)}</small></span></div>`;
  if(!inn.length&&!out.length)o+=`<p class=dim>Send a crewmate a few words. They wait on their screen even if you're far apart, and their ship's light flickers when one lands (not in quiet hours).</p>`;
  const r=lvRest();if(r)o+=`<p class="fine lvrest">${r}</p>`;
  return o+`<button class="btn sec" data-go=hail style="margin-top:var(--s3)"><span>Hail a crewmate</span><i>${Math.max(0,LV.max-LV.today)} left today</i></button></section>`;
}
// Why your ship's light won't flicker for a hail right now (it still arrives): quiet
// hours, or today's lights used up (lvflick.maybe has the rule).
function lvHM(m){return String(m/60|0).padStart(2,"0")+":"+String(m%60).padStart(2,"0")}
function lvRest(){
  if(!LV||!LV.on||!LV.light)return "";
  if(LV.quiet)return `During quiet hours (until ${lvHM(LV.quiet[1])}) hails arrive without the light.`;
  if(LV.cap&&LV.lights>=LV.cap)return `Your ship's light has flickered ${LV.cap} times today, its limit. Hails still arrive, without the light, until tomorrow.`;
  return "";
}
function lvSeen(){
  if(!LV||document.hidden)return;
  for(const x of LV.in)if(!x.seen){x.seen=1;api("/api/live/seen",{id:x.id}).catch(()=>{})}
}
const home_lv=home;home=function(){
  home_lv();
  if(S.ending!==NONE)return;
  const k=document.querySelector("#v>.kick");
  if(k&&LV)k.insertAdjacentHTML("afterend",lvHomeCard());
  if(LV&&LV.in.some((x)=>!x.seen))setTimeout(lvSeen,1200);   // they've seen it: say so (after the screen's up)
};
const crew_lv=crew;crew=function(c){
  crew_lv(c);
  if(c==null||c===S.you||c===S.here||!LV||!LV.on||S.cond[c]===2)return;
  const m=document.querySelector("#v>.me"),p=lvPeer(c),old=lvOld(p),off=lvOff(p),no=old||off;
  if(m)m.insertAdjacentHTML("afterend",`<section id=lv-crew><div class=lab><span>Ship to ship</span><span>${lvNear(c)}</span></div><button class="btn pri" data-go="hail/${c}"${no||lvOnWay(c)?" disabled":""}><span>Hail ${h(nm(c))}</span><i>${old?"needs update":off?"not right now":lvOnWay(c)?"on its way":lvNl(p)?"note only":"light + note"}</i></button>${old?`<p class=fine>${h(ship(c))} needs the latest ship software before it can be hailed.</p>`:off?`<p class=fine>${h(nm(c))}'s ship isn't taking hails right now.</p>`:lvNl(p)&&!lvOnWay(c)?`<p class=fine>${h(nm(c))}'s ship has its hail light off, so a hail shows there as a note.</p>`:""}</section>`);
};
function hailScreen(to){
  shipTop();
  if(to!=null&&LVT==null)LVT=to;
  const c=[...Array(N).keys()].filter((j)=>j!==S.here&&S.cond[j]!==2);
  let o=`<div class=kick><div class=lab>Hail · from ${h(ship(S.here))}</div><h1>${LVB?"Hail back":"Hail a crewmate"}</h1><p class=dim>${LVT!=null&&lvNl(lvPeer(LVT))?`${h(nm(LVT))}'s ship has its hail light off, so your words wait on their screen as a note.`:"Your words wait on their screen, and their ship's light flickers for a few seconds (not in quiet hours)."} Out of range? Your ship keeps trying while they're around.</p></div>`;
  o+=`<section><div class=lab><span>To</span><span>their ship</span></div>`+c.map((j)=>{const p=lvPeer(j),old=lvOld(p),off=lvOff(p),w=lvOnWay(j);return `<button class=row data-lvto=${j} aria-pressed="${LVT===j}"${old||off||w?" disabled":""}><span class=pt>${portrait(j)}</span><span class=t>${h(nm(j))}<small>${old?"Needs the latest ship software":off?"Their ship isn't taking hails right now":w?"Your last hail is on its way":lvNear(j)}</small></span><span class=lvck aria-hidden=true></span></button>`}).join("")+`</section>`;
  o+=`<section><div class=lab><span>Say</span><span>one line</span></div><div class=lvph role=radiogroup aria-label="What to say">${LV_PH.map((p,i)=>`<button role=radio data-lvph=${i} aria-checked="${LVP===i}">${h(p)}</button>`).join("")}</div><p id=lv-e class=err role=alert>${h(LVE)}</p></section>`;
  $("v").innerHTML=o;
  const ok=LVT!=null&&LVP!=null&&!LVS;
  dock(`<button class="btn pri" data-lvsend=1${ok?"":" disabled"}><span>${LVS?"Sending":"Send hail"}</span><i>${LV?Math.max(0,LV.max-LV.today)+" left today":""}</i></button>`,"");
}
function coexScreen(){
  shipTop();
  const c=LVC;
  let o=`<div class=kick><div class=lab>Settings · Ship-to-ship</div><h1>Radio check</h1><p class=dim>Your ship has one radio for its Wi-Fi and Bluetooth. This is how both are doing since it started.</p></div>`;
  if(!c)o+=`<p class=dim>Asking the ship\u2026<span class=caret></span></p>`;
  else{
    const b=c.ble,l=c.live,w=c.web,up=c.up<3600?Math.round(c.up/60)+" min":Math.round(c.up/3600)+" h";
    o+=`<section><div class=lab><span>Bluetooth sync</span><span>${b?h(b.state):"off"}</span></div>${b?`<dl class=facts><dt>Ships heard</dt><dd class=m>${b.heard}</dd><dt>Syncs</dt><dd class=m>${b.ok} ok · ${b.fail} missed</dd><dt>Links</dt><dd class=m>${b.out} out · ${b.in} in · ${b.refused} busy</dd></dl>${b.last?`<p class=fine>${h(b.last)}</p>`:""}`:`<p class=dim>Your ship's Bluetooth isn't running.</p>`}</section>`;
    o+=`<section><div class=lab><span>Hails</span><span>${l?"on":"off"}</span></div>${l?`<dl class=facts><dt>Waiting</dt><dd class=m>${l.waiting}</dd><dt>Calls</dt><dd class=m>${l.dial_ok} ok · ${l.dial_fail} missed</dd><dt>Taken</dt><dd class=m>${l.in} in · ${l.acked} delivered</dd><dt>Turned away</dt><dd class=m>${l.dup} repeats · ${l.bad} garbled</dd></dl>`:`<p class=dim>Ship-to-ship is off.</p>`}</section>`;
    o+=`<section><div class=lab><span>Wi-Fi</span><span>up ${up}</span></div><dl class=facts><dt>Answered</dt><dd class=m>${w?w.served:"—"}</dd><dt>Too busy</dt><dd class=m>${w?w.refused:"—"}</dd><dt>Free memory</dt><dd class=m>${c.heap>0?Math.round(c.heap/1024)+" KB":"\u2014"}</dd></dl></section>`;
    o+=lvTestSect();
  }
  $("v").innerHTML=o;
  const run=LVR&&LVR.run;
  dock(`<div class=tnav><button class="btn sec" data-go=set${run?" disabled":""}><span>Settings</span></button>${run?`<button class="btn pri" disabled><span>Testing\u2026</span><i>${LVR.p.length}/${LV_TN}</i></button>`:`<button class="btn pri" data-lvtest=1${c?"":" disabled"}><span>${LVR?"Test again":"Run radio test"}</span>${LVR?"":"<i>15 s</i>"}</button>`}</div>`,"");
}
// The radio test: LV_TN probes of /api/coex/ping, every other one a 4 KB piece (an update's
// size), while the ship carries on syncing. Each answer says what Bluetooth was doing as it
// started; the result splits the times by that, and counts what the radio did meanwhile.
const LV_TN=30;let LVR=null;
function lvMed(a){if(!a.length)return null;const b=a.slice().sort((x,y)=>x-y);return b[b.length>>1]}
function lvTestSect(){
  if(!LVR)return `<section id=lv-test><div class=lab><span>Radio test</span><span>${LV_TN} answers</span></div><p class=dim>Your phone asks the ship for small answers and update-sized pieces for about 15 seconds while it carries on with Bluetooth. Best run while a crewmate's ship is nearby, or straight after sending a hail.</p></section>`;
  const p=LVR.p,ok=p.filter((x)=>x.ok),bt=ok.filter((x)=>x.b!=="idle"&&x.b!=="off"),big=ok.filter((x)=>x.kb),bad=p.length-ok.length;
  const ms=(a)=>{const m=lvMed(a.map((x)=>x.ms));return m==null?"—":m+" ms"};
  const worst=ok.length?Math.max(...ok.map((x)=>x.ms))+" ms":"—";
  const kbs=big.length?Math.round(big.reduce((s,x)=>s+x.kb,0)/(big.reduce((s,x)=>s+x.ms,0)/1000))+" KB/s":"—";
  const d=LVR.d;
  let o=`<section id=lv-test><div class=lab><span>Radio test</span><span>${LVR.run?"running":p.length+" asked"}</span></div><dl class=facts><dt>Answered</dt><dd class=m>${ok.length} of ${p.length}${bad?` · <b class=lverr>${bad} missed</b>`:""}</dd><dt>Typical</dt><dd class=m>${ms(ok)}</dd><dt>Slowest</dt><dd class=m>${worst}</dd><dt>Update pieces</dt><dd class=m>${kbs}</dd><dt>Bluetooth busy</dt><dd class=m>${bt.length?bt.length+" answers · "+ms(bt):"never during the test"}</dd>${d?`<dt>Meanwhile</dt><dd class=m>${d.links} links · ${d.hails} hail calls</dd>`:""}</dl>`;
  if(!LVR.run)o+=`<p class=fine>${bad?"Some answers didn't come back. Run it again. If it keeps happening, turn Ship-to-ship off in Settings.":bt.length?"Wi-Fi kept answering while Bluetooth was busy.":"Bluetooth stayed idle this time, so this only shows Wi-Fi on its own. Try again near a crewmate's ship."}</p>`;
  return o+`</section>`;
}
async function lvTest(){
  if(LVR&&LVR.run)return;
  const c0=LVC;LVR={run:1,p:[],d:null};view();
  let busy=0;
  for(let k=0;k<LV_TN&&route==="coex";k++){
    const kb=k%2?4:0,t=performance.now();
    try{
      const r=await fetch("/api/coex/ping?kb="+kb,{headers:{"X-Crew-Token":tok},cache:"no-store"});
      const n=(await r.arrayBuffer()).byteLength;
      // review 3 m3: 503 + Retry-After is the ship's admission (another phone's state is
      // streaming), not a missed answer: wait and ask again (up to 30 times a test), so the
      // result never suggests turning Ship-to-ship off for it
      const ra=r.status===503&&+r.headers.get("Retry-After");
      if(ra&&busy<30){busy++;k--;await new Promise((f)=>setTimeout(f,Math.min(5,ra)*1000));continue}
      LVR.p.push({ok:r.ok&&n===kb*1024,ms:Math.round(performance.now()-t),kb,b:r.headers.get("X-Ble")||"off"});
      if(r.status===401){tok="";me=-1;return go("hello")}
    }catch(e){LVR.p.push({ok:false,ms:Math.round(performance.now()-t),kb,b:"?"})}
    if(route==="coex")view();
    await new Promise((f)=>setTimeout(f,300));
  }
  try{LVC=await api("/api/coex")}catch(e){}
  const a=c0&&c0.ble,b=LVC&&LVC.ble,la=c0&&c0.live,lb=LVC&&LVC.live;
  LVR.d=a&&b?{links:(b.out+b.in)-(a.out+a.in),hails:la&&lb?lb.dial-la.dial:0}:null;
  LVR.run=0;if(route==="coex")view();
}
let LVC=null;
// why Hail paused itself, in words (the ship's few fixed reasons, lvlivex.py; R2 m4: never
// an exception's text) and when: "after a problem yesterday"
function lvWhy(){
  const w=LV.why||"",d=LV.at,t=Math.floor((Date.now()-new Date().getTimezoneOffset()*60000)/86400000);
  const when=d==null?"":d===t?" today":d===t-1?" yesterday":" on "+new Date(d*86400000).toLocaleDateString("en-US",{month:"short",day:"numeric",timeZone:"UTC"});
  if(w==="no Bluetooth")return "because its Bluetooth isn't running";
  if(w==="no fleet key")return "because it isn't set up for the fleet yet";
  return "after a problem"+when;
}
function lvSect(){
  if(!LV)return `<section id=set-live></section>`;
  let o=`<section id=set-live><div class=lab><span>Ship-to-ship</span><span>${LV.on?"on":"off"}</span></div>`;
  if(!LV.on&&LV.why==="turned off"){
    o+=`<p class=dim>Hails between ships are off. Your ship still syncs the story with the fleet.</p><button class="btn sec" data-lvset=on><span>Ship-to-ship: off</span><i>turn on</i></button>`;
  }else if(!LV.on&&lvFault()){
    o+=`<p class=lvwhy>Paused on its own ${h(lvWhy())}. Your ship turned hails off to stay safe; turn them back on when you like.</p><button class="btn pri" data-lvset=on><span>Turn back on</span><i>hails</i></button>`;
  }else if(!LV.on){
    // the fleet switch (lvlive.ON, set by a release), a core it wasn't built for, no
    // Bluetooth, no fleet key, or it didn't start: no switch here would help
    o+=`<p class=lvwhy>${lvPausedWhy()}</p><button class="btn sec" disabled><span>Ship-to-ship: paused</span></button>`;
  }else{
    o+=`<p class=dim>Hails travel from your ship to a crewmate's by Bluetooth. Only what you send goes, signed with your fleet's key.</p><button class="btn sec" data-lvset=off aria-pressed=true><span>Ship-to-ship: on</span><i>turn off</i></button>`;
    o+=`<button class="btn sec" data-lvset=light aria-pressed="${LV.light}"><span>Flicker for hails: ${LV.light?"on":"off"}</span><i>${LV.light?"turn off":"turn on"}</i></button><p class=fine>${LV.light?"Your ship's light flashes on and off for about 10 s when a hail lands, whether or not the Ship light is on.":"Hails land without the light. Crewmates' phones say a hail reaches you as a note."} Never during quiet hours${LV.qw?` (${lvHM(LV.qw[0])} to ${lvHM(LV.qw[1])})`:""}, and at most ${LV.cap||12} a day (${LV.lights} so far).</p>${lvRest()?`<p class="fine lvrest">${lvRest()}</p>`:""}`;
  }
  if(LV.on)o+=`<button class="btn sec" data-lvset=dl aria-pressed="${LV.dl!==false}"><span>Flicker for your turn: ${LV.dl!==false?"on":"off"}</span><i>${LV.dl!==false?"turn off":"turn on"}</i></button><p class=fine>Two slow pulses when an invitation or a turn arrives. The light shares the hail allowance and rests in quiet hours. ${LV.dl===false?"Your turns show on your page without the light.":""}</p>`;
  return o+`<button class=go data-go=coex style="margin-top:var(--s3)"><span class=lab><span>Radio check</span><span>Wi-Fi + Bluetooth</span></span><b>How your ship's radio is doing</b></button></section>`;
}
const setScreen_lv=setScreen;setScreen=function(){
  setScreen_lv();
  const o=$("set-out");if(o)o.insertAdjacentHTML("beforebegin",lvSect());
  if(!LV)lvLoad();
};
const view_lv=view;view=function(){
  const [a,b]=route.split("/");
  if(tok&&S&&(a==="hail"||a==="coex")){
    try{
      if(a==="coex"){if(!LVC)api("/api/coex").then((j)=>{LVC=j;if(route==="coex")view()}).catch(()=>{});return coexScreen()}
      if(!LV){lvLoad();return hailScreen(b!=null?+b:null)}
      return hailScreen(b!=null?+b:null);
    }finally{if(net==="lost")$("v").insertAdjacentHTML("afterbegin","<div class=off role=status>No signal · last copy shown<button data-retry=1>Retry</button></div>")}
  }
  if(a!=="hail"){LVT=LVP=null;LVB=0;LVE=""}
  if(a!=="coex"){LVC=null;if(!(LVR&&LVR.run))LVR=null}
  if(tok&&S&&!LV&&(a==="home"||a==="crew"))lvLoad();
  return view_lv();
};
const pollV_lv=pollV;pollV=async function(){
  const j=await pollV_lv();
  if(j&&j.lv!==undefined&&j.lv!==LVV){LVV=j.lv;lvLoad()}
  return j;
};
document.addEventListener("click",async(ev)=>{
  const t=ev.target.closest("[data-lvto],[data-lvph],[data-lvsend],[data-lvbk],[data-lvset],[data-lvtest]");if(!t||t.disabled)return;
  const d=t.dataset;
  if(d.lvtest!=null)return lvTest();
  if(d.lvto!=null){LVT=+d.lvto;LVE="";return view()}
  if(d.lvph!=null){LVP=+d.lvph;LVE="";view();return document.querySelector(`[data-lvph="${LVP}"]`)?.focus()}
  if(d.lvbk!=null){LVT=+d.lvbk;LVB=1;LVP=null;return go("hail")}
  if(d.lvsend!=null){
    LVS=1;LVE="";view();
    try{await api("/api/live/hail",{to:LVT,ph:LVP,back:LVB});LVS=0;LVT=LVP=null;LVB=0;await lvLoad();return go("home")}
    catch(e){LVS=0;if(!tok)return;LVE=e.message||"That didn't go. Try again.";return view()}
  }
  if(d.lvset!=null){
    const k=d.lvset,b=k==="on"?{on:true}:k==="off"?{on:false}:{[k]:!LV[k]};
    t.disabled=true;
    try{await api("/api/live/set",b)}catch(e){}
    await lvLoad();lvPaint();
  }
});

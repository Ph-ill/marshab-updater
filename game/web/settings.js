// Settings (web/settings.css): the gear at the top right of every signed-in screen opens one
// page for this phone and this ship: Ship software (web/ota.js: what runs, what's ready,
// install, check), the home-screen icon steps (web/a2hs.js), the Ship light, the battery
// (web/batt.js; only on a ship that has one), signing this phone out, and resetting the ship.
// The crew page is only about the crew; the four tabs stay as they are. Hooked onto
// app.html's shipTop/view from here, like the others; loaded last, so it sees their hooks.
// Reset this ship (board/main.py reset_ship, POST /api/reset): only for a signed-in crew
// member who also types this ship's number; the ship deletes the players' progress and
// restarts (keeps its settings, crew codes and software), then this page forgets everything
// it kept in this browser and starts again at the sign-in.
// Change your code (board/lvcode.py, POST /api/code {old, new}): under Sign out, above
// Reset. Your code now, then the new one twice, 4 digits each (the sign-in's own rule). The
// page checks the format and that the two new ones match before asking; the ship checks the
// current code against the sign-in's tries and lockout, saves the new one in crew.json and
// keeps this phone signed in. Only this ship's copy changes, and the row says so.
// Test light, under the Ship light switch: see ledtHTML below.
const SET_GEAR="M15.9 8L18 8.4v3.2l-2.1.4-.4.8 1.3 1.7-2.3 2.3-1.7-1.3-.8.4-.4 2.1H8.4L8 15.9l-.8-.4-1.7 1.3-2.3-2.3 1.3-1.7-.4-.8L2 11.6V8.4L4.1 8l.4-.8-1.3-1.7 2.3-2.3 1.7 1.3.8-.4.4-2.1h3.2l.4 2.1.8.4 1.7-1.3 2.3 2.3-1.3 1.7ZM7 10a3 3 0 1 0 6 0a3 3 0 1 0-6 0Z";
let RST=null;   // the reset row: null, "ask" (typing the number), "send", or an error message
let CHG=null;   // the code row: null, "ask" (the form), "send", "done", or {err, f: the field to fix}
let CHGV=null;  // what was typed, kept across a redraw while the form is open
const shipTop1=shipTop;shipTop=function(){
  shipTop1();
  const s=$("top")&&$("top").querySelector("span");if(!s)return;
  const dot=typeof otaNag==="function"&&otaNag();
  s.insertAdjacentHTML("beforeend",`<button class="gear${dot?" dot":""}" data-go=set aria-label="Settings${dot?", update ready":""}"${route==="set"?" aria-current=page":""}><svg viewBox="0 0 20 20" aria-hidden=true><path d="${SET_GEAR}"/></svg></button>`);
};
function setNo(){return S.here+1}
function setScreen(){
  shipTop();
  const k=a2Kind(),b=S.bat,n=setNo();
  let o=`<div class=kick><div class=lab>This phone · LV-${n}</div><h1>Settings</h1></div>`;
  o+=otaSect();
  o+=`<section id=set-a2h><div class=lab><span>Home screen icon</span>${k?`<span>${a2Steps(k).split("<li>").length-1} steps</span>`:""}</div>${k?`<p class=a2l>Keep the game one tap away. It opens ${a2Opens(k)}.</p>${a2Steps(k)}<p class=fine>${A2_WIFI}</p>`:`<p class=dim>${a2Std()?"You're already playing from your home screen.":"Open the game in your phone's browser to put it on your home screen."}</p>`}</section>`;
  if(S.led!=null)o+=`<section id=set-led><div class=lab><span>Ship light</span><span>${S.led?"on":"off"}</span></div><p class=dim>Your ship's light pulses softly when something's waiting, no phone needed.</p><button class="btn sec" data-led=1 aria-pressed="${!!S.led}"><span>Ship light: ${S.led?"on":"off"}</span><i>${S.led?"turn off":"turn on"}</i></button>${LEDW?`<p id=ledw class=err role=alert>${h(LEDW)}</p>`:""}${ledtHTML(n)}</section>`;
  if(b)o+=`<section id=set-bat><div class=lab><span>Battery</span></div>${batFacts(b)}</section>`;
  o+=`<section id=set-out><div class=lab><span>This phone</span></div><button class="btn sec" data-out=1><span>Not ${h(nm(S.you))}? Sign out</span><i>this phone</i></button></section>`;
  o+=chgSect(n);
  o+=`<section id=set-rst class=rst><div class="lab r"><span>Reset this ship</span><span>can't be undone</span></div><p class=dim>Starts LV-${n} over: everyone's progress on it goes (the log, votes, gifts, hails, sign-ins) and it restarts. Its name, Wi-Fi password and software stay. Ships in range may sync their records back.</p>`;
  if(RST==null)o+=`<button class="btn dgr" data-rst=ask><span>Reset this ship</span><i>LV-${n}</i></button>`;
  else o+=`<label class=rstl for=rstn>Type <b class=m>${n}</b>, this ship's number, to confirm</label><input id=rstn class=m inputmode=numeric autocomplete=off maxlength=2 aria-describedby=rste><p id=rste class=err role=alert>${RST!=="ask"&&RST!=="send"?h(RST):""}</p><div class=rstb><button class="btn dgr" data-rst=go disabled><span>${RST==="send"?"Resetting":"Reset"}</span><i>restarts</i></button><button class="btn sec" data-rst=no><span>Cancel</span></button></div>`;
  o+=`</section>`;
  $("v").innerHTML=o;
  dock("","set");
}
// Test light (board/lvledtest.py, POST /api/led/test): the ship plays three blinks and three
// slow pulses (10 s; 0.3.0, was ~4 s), on or off, then goes back to what its light was doing. The button says
// "Testing" with a thin bar for as long as the ship says it plays; repainted in place (never a
// whole redraw: the code form keeps what's typed), and a tap meanwhile does nothing.
let LEDT=0,LEDS=0,LEDE="",LEDK=0;   // test: ends at (Date.now ms), started at, last error, timer
let LEDH=0;     // a hail's flicker has the light until (Date.now ms): Test light says so (review 3 m2)
let LEDW="";    // the Ship light switch's last refusal (app.html's data-led click), shown under it
function ledtHTML(n){
  const now=Date.now(),on=LEDT>now,ms=LEDT-LEDS;
  let o=`<div id=set-ledt><button class="btn sec ledt" data-ledt=1${on?" disabled aria-busy=true":""} aria-describedby=ledts><span>${on?"Testing\u2026":"Test light"}</span><i>${on?"watch LV-"+n:"10 s"}</i>${on?`<b class=ledbar style="animation-duration:${ms}ms;animation-delay:-${now-LEDS}ms" aria-hidden=true></b>`:""}</button>`;
  const hl=LEDH>now?Math.ceil((LEDH-now)/1000):0;
  o+=`<p id=ledts class=${LEDE?"err":"fine"} role=status>${LEDE?h(LEDE):hl?`Your ship's light is showing a hail. Try again in ${hl} s.`:on?`Look at LV-${n} now: three blinks, then three slow pulses.`:LEDS?`Finished. The light is back to ${S.led?"on":"off"}.`:"Three blinks, then three slow pulses. Works with the light off too."}</p></div>`;
  return o;
}
function ledtPaint(){
  const d=$("set-ledt");if(!d)return;
  const f=d.contains(document.activeElement);d.outerHTML=ledtHTML(setNo());
  if(f)document.querySelector("[data-ledt]")?.focus();
}
function ledtFor(ms){
  ms=Math.max(0,+ms||0);LEDS=Date.now();LEDT=LEDS+ms;clearTimeout(LEDK);
  LEDK=setTimeout(()=>{LEDT=0;ledtPaint()},ms+250);ledtPaint();
}
document.addEventListener("click",async(ev)=>{
  const el=ev.target.closest("button[data-ledt]");if(!el||el.disabled||LEDT>Date.now())return;
  LEDE="";LEDH=0;ledtFor(10000);
  try{const j=await api("/api/led/test",{});ledtFor(j.ms??10000)}
  catch(e){
    if(!tok)return;
    if(e.status===429&&e.j&&e.j.kind==="hail"){
      // review 3 m2: a hail's flicker has the light (dark while it waits, then 3 Hz), so not
      // "three blinks": say what it is and when to try again
      clearTimeout(LEDK);LEDT=LEDS=0;LEDH=Date.now()+Math.max(1000,+e.j.ms||0);ledtPaint();
      LEDK=setTimeout(()=>{LEDH=0;ledtPaint()},LEDH-Date.now()+250);return;
    }
    if(e.status===429)return ledtFor(e.j&&e.j.ms);
    clearTimeout(LEDK);LEDT=LEDS=0;LEDE=e.message||"That didn't work. Try again.";ledtPaint();
  }
});
const CHG_F=[["chg0","Your code now"],["chg1","New code"],["chg2","New code again"]];
function chgSect(n){
  let o=`<section id=set-code><div class=lab><span>Your code</span><span>LV-${n} only</span></div>`;
  if(CHG==null||CHG==="done"){
    o+=CHG==="done"?`<p class=ok role=status>Done. Sign in on LV-${n} with your new code from now on. You're still signed in here.</p>`:`<p class=dim>The 4 digits you sign in with on LV-${n}. Other ships keep your current code.</p>`;
    return o+`<button class="btn sec" data-chg=ask><span>Change your code</span><i>4 digits</i></button></section>`;
  }
  const e=CHG&&CHG.err,v=CHGV||["","",""];
  o+=`<p class=dim>Type your current code, then the new one twice.</p><div class=chgf>`;
  CHG_F.forEach(([id,l],i)=>{o+=`<label for=${id}>${l}</label><input id=${id} class="m pinf${e&&CHG.f===i?" bad":""}" type=text inputmode=numeric pattern="[0-9]*" maxlength=4 autocomplete=off autocorrect=off autocapitalize=off spellcheck=false enterkeyhint=${i<2?"next":"done"} aria-describedby=chge${e&&CHG.f===i?" aria-invalid=true":""} value="${h(v[i])}">`});
  o+=`</div><p id=chge class=err role=alert>${e?h(e):""}</p><div class=rstb><button class="btn pri" data-chg=go${CHG==="send"?" disabled":""}><span>${CHG==="send"?"Saving":"Save"}</span><i>new code</i></button><button class="btn sec" data-chg=no><span>Cancel</span></button></div></section>`;
  return o;
}
function chgVals(){return CHG_F.map(([id])=>($(id)?$(id).value:"").trim())}
function chgErr(err,f){CHG={err,f};CHGV=chgVals();if(f===1||f===2){CHGV[1]=CHGV[2]=""}if(f===0)CHGV[0]="";view();const i=$(CHG_F[f][0]);if(i)i.focus()}
async function chgGo(){
  const [a,b,c]=chgVals(),four=(x)=>/^\d{4}$/.test(x);
  if(!four(a))return chgErr("Your current code is 4 digits.",0);
  if(!four(b))return chgErr("Your new code needs to be 4 digits.",1);
  if(b!==c)return chgErr("The two new codes don't match. Type them again.",1);
  if(a===b)return chgErr("Your new code is the same as your current one.",1);
  CHGV=[a,b,c];CHG="send";view();
  try{await api("/api/code",{old:a,new:b});CHG="done";CHGV=null;view();const r=document.querySelector("[data-chg=ask]");if(r)r.focus()}
  catch(e){
    if(!tok)return;
    const s=e.status,j=e.j||{};
    if(s===403)return chgErr("That isn't your current code. "+(j.left==null?"":j.left+" "+(j.left===1?"try":"tries")+" left."),0);
    if(s===429){const m=Math.max(1,Math.ceil((j.wait||60)/60));return chgErr("Too many tries. Signing in and changing your code are paused for "+m+" min.",0)}
    return chgErr(e.message||"That didn't work. Try again.",s===400&&/new/i.test(e.message)?1:0);
  }
}
function setDone(ms){
  // The ship is restarting without anyone's progress: so does this page, signed out.
  const wipe=()=>{try{localStorage.clear();sessionStorage.clear()}catch(e){}};
  wipe();
  if(ws){ws.onclose=ws.onerror=null;ws.close();ws=null}
  clearInterval(poll);poll=0;net="live";tok="";me=-1;S=null;RST=null;route="hello";history.replaceState(null,"",location.pathname+location.search);
  bar("THE LONG VOYAGE","RESTARTING");
  $("v").innerHTML=`<div class=kick role=status><div class=lab>Reset</div><h1>Starting over</h1><p class=dim>Your ship is clearing its progress and restarting. This page forgot what it kept on this phone and opens at the sign-in once the ship is back, in about half a minute.<span class=caret></span></p></div>`;
  dock("","");
  setTimeout(async()=>{
    const t0=Date.now();
    while(Date.now()-t0<150e3){
      try{const c=new AbortController(),t=setTimeout(()=>c.abort(),3000);const r=await fetch("/api/crew",{cache:"no-store",signal:c.signal});clearTimeout(t);if(r.ok)break}catch(e){}
      await new Promise((ok)=>setTimeout(ok,2500));
    }
    wipe();location.reload();
  },(ms||1500)+4000);
}
const view_set=view;view=function(){
  if(/^(set|sw|a2h)$/.test(route)&&tok&&S){
    if(route!=="set"){route="set";history.replaceState(null,"","#set")}
    try{return OI?otaScreen():OH?otaHist():setScreen()}finally{if(net==="lost"&&!OI)$("v").insertAdjacentHTML("afterbegin","<div class=off role=status>No signal · last copy shown<button data-retry=1>Retry</button></div>")}
  }
  if(route!=="set"){RST=null;CHG=null;CHGV=null;OH=null;if(!(LEDT>Date.now()))LEDS=0,LEDE=""}
  return view_set();
};
document.addEventListener("input",(ev)=>{
  const t=ev.target;
  if(/^chg[012]$/.test(t.id)){const d=t.value.replace(/\D/g,"").slice(0,4);if(d!==t.value)t.value=d;if(t.classList.contains("bad")){t.classList.remove("bad");t.removeAttribute("aria-invalid")}if(d.length===4&&t.id!=="chg2")$("chg"+(+t.id[3]+1))?.focus();return}
  if(t.id!=="rstn")return;
  const b=document.querySelector("[data-rst=go]");if(b)b.disabled=RST==="send"||ev.target.value.trim()!==String(setNo());
});
document.addEventListener("keydown",(ev)=>{if(ev.key==="Enter"&&/^chg[012]$/.test(ev.target.id)){ev.preventDefault();if(ev.target.id==="chg2")chgGo();else $("chg"+(+ev.target.id[3]+1))?.focus()}});
document.addEventListener("click",(ev)=>{
  const el=ev.target.closest("button[data-chg]");if(!el||el.disabled)return;
  const k=el.dataset.chg;
  if(k==="ask"){CHG="ask";CHGV=null;view();return $("chg0")?.focus()}
  if(k==="no"){CHG=null;CHGV=null;view();return document.querySelector("[data-chg=ask]")?.focus()}
  if(k==="go"&&CHG!=="send")chgGo();
});
document.addEventListener("click",async(ev)=>{
  const el=ev.target.closest("button[data-rst]");if(!el||el.disabled)return;
  const k=el.dataset.rst;
  if(k==="ask"){RST="ask";view();return $("rstn")?.focus()}
  if(k==="no"){RST=null;return view()}
  const v=$("rstn").value.trim();if(v!==String(setNo()))return;
  RST="send";el.disabled=true;el.querySelector("span").textContent="Resetting";
  try{const j=await api("/api/reset",{confirm:+v});return setDone(j.restart_ms)}
  catch(e){if(!tok)return;RST=e.message||"That didn't work. Try again.";view();const i=$("rstn");if(i){i.value=v;i.focus();i.dispatchEvent(new Event("input",{bubbles:true}))}}
});

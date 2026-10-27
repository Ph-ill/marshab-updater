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
const SET_GEAR="M15.9 8L18 8.4v3.2l-2.1.4-.4.8 1.3 1.7-2.3 2.3-1.7-1.3-.8.4-.4 2.1H8.4L8 15.9l-.8-.4-1.7 1.3-2.3-2.3 1.3-1.7-.4-.8L2 11.6V8.4L4.1 8l.4-.8-1.3-1.7 2.3-2.3 1.7 1.3.8-.4.4-2.1h3.2l.4 2.1.8.4 1.7-1.3 2.3 2.3-1.3 1.7ZM7 10a3 3 0 1 0 6 0a3 3 0 1 0-6 0Z";
let RST=null;   // the reset row: null, "ask" (typing the number), "send", or an error message
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
  if(S.led!=null)o+=`<section id=set-led><div class=lab><span>Ship light</span><span>${S.led?"on":"off"}</span></div><p class=dim>Your ship's light pulses softly when something's waiting, no phone needed.</p><button class="btn sec" data-led=1 aria-pressed="${!!S.led}"><span>Ship light: ${S.led?"on":"off"}</span><i>${S.led?"turn off":"turn on"}</i></button></section>`;
  if(b)o+=`<section id=set-bat><div class=lab><span>Battery</span></div><dl class=facts><dt>Charge</dt><dd class=m>${b[0]==null?"—":b[0]+"%"}</dd><dt>Voltage</dt><dd class=m>${b[1]?(b[1]/1000).toFixed(2)+" V":"—"}</dd><dt>Charging</dt><dd>${b[2]?"Yes":"No"}</dd></dl></section>`;
  o+=`<section id=set-out><div class=lab><span>This phone</span></div><button class="btn sec" data-out=1><span>Not ${h(nm(S.you))}? Sign out</span><i>this phone</i></button></section>`;
  o+=`<section id=set-rst class=rst><div class="lab r"><span>Reset this ship</span><span>can't be undone</span></div><p class=dim>Starts LV-${n} over: everyone's progress on it goes (the log, votes, gifts, sign-ins) and it restarts. Its name, Wi-Fi password and software stay. Ships in range may sync their records back.</p>`;
  if(RST==null)o+=`<button class="btn dgr" data-rst=ask><span>Reset this ship</span><i>LV-${n}</i></button>`;
  else o+=`<label class=rstl for=rstn>Type <b class=m>${n}</b>, this ship's number, to confirm</label><input id=rstn class=m inputmode=numeric autocomplete=off maxlength=2 aria-describedby=rste><p id=rste class=err role=alert>${RST!=="ask"&&RST!=="send"?h(RST):""}</p><div class=rstb><button class="btn dgr" data-rst=go disabled><span>${RST==="send"?"Resetting":"Reset"}</span><i>restarts</i></button><button class="btn sec" data-rst=no><span>Cancel</span></button></div>`;
  o+=`</section>`;
  $("v").innerHTML=o;
  dock("","set");
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
    try{return OI?otaScreen():setScreen()}finally{if(net==="lost"&&!OI)$("v").insertAdjacentHTML("afterbegin","<div class=off role=status>No signal · last copy shown<button data-retry=1>Retry</button></div>")}
  }
  if(route!=="set")RST=null;
  return view_set();
};
document.addEventListener("input",(ev)=>{
  if(ev.target.id!=="rstn")return;
  const b=document.querySelector("[data-rst=go]");if(b)b.disabled=RST==="send"||ev.target.value.trim()!==String(setNo());
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

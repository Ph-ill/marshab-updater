// Safe mode (board/lvsafe.py): after two crashes in a row the ship comes up with only its
// hotspot, the sign-in and Settings › Ship software, so an update can still reach it. The
// ship says so in /api/crew {safe} and answers /api/state 503 {safe}. This page then shows
// one screen: what happened in plain words, the update section (web/ota.js otaSect: what
// runs, what's on this phone, Install) and "Try the game again" (POST /api/safe/retry: the
// ship restarts and gives the game one more go). The ship also tries the game again on its
// own after a while (retry_s: 30 min, then longer each time); the screen says when, in this
// phone's time. Anyone on the hotspot sees the count and the kind of crash; the crash's own
// words (detail) come only with a signed-in /api/state. No story, no tabs. Hooked onto
// app.html's api/refresh/view/shipTop/dock here, before ota.js and settings.js wrap them.
let SAFE="",SAFE_D="",SAFE_AT=0;
function safeAt(s){if(typeof s==="number")SAFE_AT=Date.now()+s*1000}
const api_safe=api;api=async function(p,b){
  try{const j=await api_safe(p,b);if(p==="/api/crew"){SAFE=j.safe||"";safeAt(j.retry_s)}return j}
  catch(e){if(e.status===503&&e.j&&e.j.safe){SAFE=e.j.safe;SAFE_D=e.j.detail||"";safeAt(e.j.retry_s);if(poll){clearInterval(poll);poll=0}}throw e}
};
const refresh_safe=refresh;refresh=async function(){
  try{await refresh_safe()}catch(e){if(!(SAFE&&e.status===503))throw e;S=null;view()}
};
const shipTop_safe=shipTop;shipTop=function(){if(SAFE&&!S)return bar("THE LONG VOYAGE","SAFE MODE");shipTop_safe()};
const dock_safe=dock;dock=function(html,tabs){return dock_safe(html,SAFE&&!S?"":tabs)};
let SAFE_GO=0;
function safeScreen(){
  if(typeof OI!=="undefined"&&OI)return otaScreen();
  shipTop();
  const n=parseInt(SAFE,10)||2;
  let o=`<div class=kick role=status><div class="lab r">Safe mode</div><h1>Your ship is resting</h1><p class=lead>It stopped unexpectedly ${n===2?"twice":n+" times"} in a row, so it started with only its Wi-Fi and this screen.</p><p class=dim>The story, Bluetooth and the light are paused. Your crew, log and votes are kept on the ship.</p></div>`;
  o+=typeof otaSect==="function"?otaSect():"";
  const at=SAFE_AT>Date.now()?new Date(SAFE_AT).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}):"";
  o+=`<section id=safe-retry><div class=lab><span>The game</span></div><p class=dim>${at?`Your ship tries the game again on its own at about ${h(at)}. `:""}If it stops again, it comes back here. An update is the better fix when there is one.</p>${SAFE_D?`<p class=fine>Last stop: ${h(SAFE_D)}</p>`:""}${SAFE_GO===1?`<p class=fine>Restarting. Rejoin your ship's Wi-Fi if this phone drops off, then reload.</p>`:SAFE_GO?`<p class=err role=alert>${h(SAFE_GO)}</p>`:""}</section>`;
  $("v").innerHTML=o;
  dock(`<button class="btn sec" data-safe=retry${SAFE_GO===1?" disabled":""}><span>${SAFE_GO===1?"Restarting":"Try the game again"}</span><i>restarts</i></button>`,"");
}
const view_safe=view;view=function(){
  if(SAFE&&tok&&!S)return safeScreen();
  view_safe();
  if(SAFE&&!tok&&$("v")&&!$("safe-n"))$("v").insertAdjacentHTML("afterbegin",`<div id=safe-n class=off role=status>Safe mode · sign in to update your ship</div>`);
};
document.addEventListener("click",async(ev)=>{
  const el=ev.target.closest("button[data-safe]");if(!el||el.disabled)return;
  el.disabled=true;
  try{const j=await api("/api/safe/retry",{});SAFE_GO=1;view();setTimeout(()=>location.reload(),(j.restart_ms||1500)+8000)}
  catch(e){SAFE_GO=e.message||"That didn't work. Try again.";view()}
});

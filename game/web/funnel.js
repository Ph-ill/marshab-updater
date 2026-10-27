// The home-screen funnel (web/funnel.css; board/lvfunnel.py; docs/OTA.md "The home-screen
// funnel"). Joining the ship's Wi-Fi is everyone's first contact with the game, and that
// first visit has one job: put the game on the phone's home screen, smoothly, once. Before
// the game loads, fnGate() asks the ship what it has seen THIS phone do (GET /api/hello)
// and shows one of:
//   LEAVE        the captive pop-up (iOS sheet, Android sign-in window). It can't add icons
//                and forgets everything when it closes, so only: how to get to the real
//                browser, and the ship's address.
//   LEAVE_KNOWN  the same, for a phone the ship has seen open the game from its icon.
//   ADD          a browser tab: a welcome card (the approved intro), then illustrated
//                steps for this browser, drawn in the game's own style.
//   OPEN         a browser tab on a phone that has the icon: use that, or play here anyway.
//   GAME         the icon itself, a computer, or "play here this time".
// Only an icon launch marks a phone installed: on iOS the page runs standalone. Android's
// shortcut opens a Chrome tab at the address it was added from, so while the guide shows,
// the address carries ?src=icon (history.replaceState; the manifest's start_url has it too).
// A reload or back/forward of a marked address isn't a launch, nor is the tab that showed
// the guide (sessionStorage outlives a reload and a restored tab; a shortcut opens a new
// tab). The ship never answers the portal checks with "internet OK", so the pop-up comes up
// whenever the phone joins; for a phone with the icon it says to use the icon.
const FN={k:"",n:0,cards:null,done:null,boot:"",scr:"",tap:false};
function fnStore(s,k,v){try{const st=window[s];if(v===undefined)return st.getItem(k);v===null?st.removeItem(k):st.setItem(k,v)}catch(e){}return null}
const fnSS=(k,v)=>fnStore("sessionStorage",k,v),fnLS=(k,v)=>fnStore("localStorage",k,v);
function fnSeen(){return fnSS("lv.fnseen")==="1"}       // web/a2hs.js: no home card after the guide
function fnCtx(){return a2Std()?"standalone":a2Kind()||"other"}
function fnAnd(){return /^(and|sam)$/.test(FN.k)}
function fnNav(){try{return performance.getEntriesByType("navigation")[0].type||"navigate"}catch(e){return "navigate"}}
function fnMarked(){return /[?&]src=icon(&|$)/.test(location.search)}
function fnMark(on){
  if(fnMarked()===on)return;
  const p=new URLSearchParams(location.search);on?p.set("src","icon"):p.delete("src");
  const q=p.toString();
  try{history.replaceState(history.state,"",location.pathname+(q?"?"+q:"")+location.hash)}catch(e){}
}
async function fnHello(icon){
  const c=window.AbortController?new AbortController():null,t=setTimeout(()=>c&&c.abort(),4000);
  try{
    const r=await fetch(`/api/hello?ctx=${FN.k}${icon?"&m=icon":""}`,{cache:"no-store",signal:c&&c.signal,
      headers:{"X-Phone-Time":String(Date.now()),"X-Phone-TZ":String(-new Date().getTimezoneOffset())}});
    return r.ok?await r.json():null;
  }catch(e){return null}finally{clearTimeout(t)}
}
function fnDecide(rec){
  const k=FN.k,inst=!!(rec&&rec.installed)||(fnAnd()&&fnLS("lv.icon")==="1");
  if(k==="sheet"||k==="awv")return inst?"LEAVE_KNOWN":"LEAVE";
  return inst?"OPEN":"ADD";
}
// Resolves when the game may load.
function fnGate(){
  const k=FN.k=fnCtx();
  const launch=fnAnd()&&fnMarked()&&!/^(reload|back_forward)$/.test(fnNav())&&fnSS("lv.fnadd")!=="1";
  if(launch){fnSS("lv.icon","1");fnLS("lv.icon","1");fnMark(false)}
  if(k==="other")return Promise.resolve();
  // The icon: tell the ship (it marks the phone installed), but don't wait for it.
  if(k==="standalone"||launch){fnHello(true);return Promise.resolve()}
  if(k!=="sheet"&&k!=="awv"&&(fnSS("lv.here")==="1"||fnSS("lv.icon")==="1")){fnHello(false);return Promise.resolve()}
  FN.boot=$("v").innerHTML;
  return new Promise((res)=>{FN.done=res;fnHello(false).then((r)=>fnShow(fnDecide(r)))});
}
function fnShow(s,n){
  FN.scr=s;
  if(s==="GAME"){
    fnMark(false);bar("THE LONG VOYAGE","CONNECTING");$("v").innerHTML=FN.boot;dock("","");scrollTo(0,0);
    const d=FN.done;FN.done=null;return d&&d();
  }
  if(s==="ADD"){fnSS("lv.fnadd","1");fnSS("lv.fnseen","1");if(fnAnd())fnMark(true);return fnCard(n|0)}
  fnMark(false);
  s==="OPEN"?fnOpen():fnLeave(s==="LEAVE_KNOWN");
}
// The heading takes focus after a tap (screen readers start there), not on the first screen.
function fnFocus(){scrollTo(0,0);if(FN.tap)requestAnimationFrame(()=>$("th")&&$("th").focus({preventScroll:true}))}

// ---- the drawings: the phone's own screens, simplified, in the game's colours -----------
// Rust rings and numbers mark what to tap, in order. No screenshots, nothing personal.
const FG=(d)=>`<svg class=a2i viewBox="0 0 16 16" aria-hidden=true><path d="${d}"/></svg>`;
const FX={bm:FG("M4 1.5h8v13l-4-3-4 3z"),find:FG("M3.5 1.5h9v13h-9zM6 5h4M6 8h4M6 11h2"),add:FG("M2.5 2.5h11v11h-11zM8 5v6M5 8h6"),
  copy:FG("M5.5 5.5h8v8h-8zM2.5 10.5v-8h8"),rl:FG("M1 9.5a3 3 0 1 0 6 0a3 3 0 1 0-6 0M9 9.5a3 3 0 1 0 6 0a3 3 0 1 0-6 0M7 9h2"),
  re:FG("M13 8a5 5 0 1 1-1.6-3.7M13.5 1.5v3.5H10"),back:FG("M10 2.5 4.5 8l5.5 5.5"),fwd:FG("M6 2.5 11.5 8 6 13.5"),
  x:FG("M4 4l8 8M12 4l-8 8"),tabs:FG("M2.5 4.5h9v9h-9zM5 2h8.5v8.5"),info:FG("M8 7v5M8 4v1.5M1.5 8a6.5 6.5 0 1 0 13 0a6.5 6.5 0 1 0-13 0"),
  book:FG("M1.5 3c2.5-1 4.5-1 6.5.5V14c-2-1.5-4-1.5-6.5-.5zM14.5 3c-2.5-1-4.5-1-6.5.5V14c2-1.5 4-1.5 6.5-.5z")};
const fnN=(i)=>`<b class=fnn>${i}</b>`;
const fnFx=(o,c)=>`<figure class="fx${c?" "+c:""}" aria-hidden=true>${o}</figure>`;
const fnAd=()=>h(location.host||"192.168.4.1");
const fnApp=(cls)=>`<img class="fnic${cls?" "+cls:""}" src="/icon.png" alt="">`;
// The home screen, with the game's icon among placeholder apps.
function fxHome(n){
  let o="";for(let i=0;i<8;i++)o+=i===5?`<span class="me hl">${fnApp()}${n?fnN(n):""}<i>The Long Voyage</i></span>`:`<span><em></em><i></i></span>`;
  return fnFx(`<div class=hs>${o}</div>`,"hsf");
}
// Safari's address bar (iOS 26: one bar at the bottom, the page menu at its left).
const fxSafari=(n)=>`<div class=sfb><span class="ui c">${FX.back}</span><span class="ui ad"><span class="pm hl">${A2_PM}${fnN(n)}</span><span class=u>${fnAd()}</span>${FX.re}</span><span class="ui c">${A2_MH}</span></div>`;
function fxShare(i26,a,b){
  const btn=(g,t,hl)=>`<span${hl?" class=hl1":""}><i class="c${hl?" hl":""}">${g}${hl?fnN(a):""}</i>${t}</span>`;
  return `<div class="ui sh"><div class=hd>${fnApp()}<span><b>The Long Voyage</b><i>${fnAd()}</i></span><span class=c>${FX.x}</span></div>`+
    (i26?`<div class=rb>${btn(FX.copy,"Copy")}${btn(FX.bm,"Add to Bookmarks")}${btn(FX.rl,"Add to Reading List")}${btn(A2_VM,"View More",1)}</div>`:"")+
    `<div class=ls>${i26?"":`<div class=r>${FX.copy}<span>Copy</span></div><div class=r>${FX.rl}<span>Add to Reading List</span></div>`}<div class=r>${FX.find}<span>Find on Page</span></div><div class="r hl">${FX.add}<span>Add to Home Screen</span>${fnN(b)}</div></div></div>`;
}
function fxDialog(i26){
  return `<div class="ui dl"><div class=dh><span>Cancel</span><b>Add to Home Screen</b><span class="ok hl">Add${fnN(i26?2:1)}</span></div>`+
    `<div class=di>${fnApp()}<span><b class=nm>The Long Voyage</b><i>${fnAd()}</i></span></div>`+
    (i26?`<div class="tg hl"><span>Open as Web App</span><i class=sw></i>${fnN(1)}</div>`:"")+`</div>`;
}
// Chrome on Android: the address bar at the top, the menu under the three dots.
const fxChrome=()=>`<div class="ui cb"><span class=ad>${FX.info}<span class=u>${fnAd()}</span></span><span class=tb>1</span><span class="mv hl">${A2_MV}${fnN(1)}</span></div>`+
  `<div class="ui mn am"><div class=r>New tab</div><div class=r>History</div><div class=r>Bookmarks</div><div class="r hl">Add to Home screen${fnN(2)}</div></div>`;

// ---- the cards ----------------------------------------------------------------------------
function fnCards(){
  if(FN.cards)return FN.cards;
  const k=FN.k,u=navigator.userAgent,v=+((u.match(/Version\/(\d+)/)||[])[1]||0);
  const i26=v>=26||!!(window.CSS&&CSS.supports("anchor-name:--a")),and=fnAnd();
  const where=k==="ios"?"Safari":k==="iosx"?"Your browser":k==="sam"?"Samsung Internet":"Chrome";
  const L=[{k:"The goal",t:"Get to Mars, together",
    p:"Eight crews fly eight Starships from Earth orbit to Mars orbit, one flight day at a time. You'll be one of them. First, a minute to put the game on your home screen.",
    fx:tFig(2),li:[["Wi-Fi","Your phone joins the ship it's next to. No internet, no app."],
      ["Bluetooth","Ships near each other swap news by themselves, even while you're away."],
      ["Daily","A new flight day starts each day, real time. Check in daily: plans land the next day, and questions close on set days."],
      ["The icon",`One tap opens the game${and?"":" full screen"}, whenever you're by the ship.`]]}];
  const last={k:where,t:"Open it from the icon",
    p:and?`Tap <b>The Long Voyage</b> on your home screen. It opens the game in a Chrome tab: tap ${A2_FS} at the top for full screen. This page notices, and stops showing these steps.`
      :`Tap <b>The Long Voyage</b> on your home screen. The game opens full screen, without the browser's bars. This page notices, and stops showing these steps.`,
    fx:fxHome(1),fine:A2_WIFI};
  if(k==="ios"&&i26)L.push(
    {k:where,t:"Open Share",p:`Tap ${A2_PM} at the left of the address bar, then <b>Share</b> at the top of the menu.`,
      fx:fnFx(`<div class="ui mn"><div class="r hl">${A2_SH}<span>Share</span>${fnN(2)}</div><div class=r>${FX.bm}<span>Add to Bookmarks</span></div><div class=r>${FX.find}<span>Find on Page</span></div></div>`+fxSafari(1),"low"),
      fine:"Share is a button in Safari's toolbar instead? Tap that."},
    {k:where,t:"Add to Home Screen",p:`In the share sheet, tap <b>View More</b> ${A2_VM}, then <b>Add to Home Screen</b> at the end of the list.`,fx:fnFx(fxShare(1,1,2))},
    {k:where,t:"Keep it a web app",p:"Leave <b>Open as Web App</b> on, so the game opens full screen. Then tap <b>Add</b>.",fx:fnFx(fxDialog(1))});
  else if(k==="ios")L.push(
    {k:where,t:"Open Share",p:`Tap <b>Share</b> ${A2_SH} in Safari's toolbar${/iPad|Macintosh/.test(u)?", at the top":", at the bottom"}.`,
      fx:fnFx(`<div class="ui tbr"><span>${FX.back}</span><span>${FX.fwd}</span><span class=hl>${A2_SH}${fnN(1)}</span><span>${FX.book}</span><span>${FX.tabs}</span></div>`,"low")},
    {k:where,t:"Add to Home Screen",p:"Scroll down the share sheet and tap <b>Add to Home Screen</b>.",fx:fnFx(fxShare(0,0,1))},
    {k:where,t:"Add it",p:"Keep the name, <b>The Long Voyage</b>, and tap <b>Add</b>.",fx:fnFx(fxDialog(0))});
  else if(k==="and")L.push(
    {k:where,t:"Open Chrome's menu",p:`Tap ${A2_MV} at the top right of Chrome, then <b>Add to Home screen</b>.`,fx:fnFx(fxChrome())},
    {k:where,t:"Add the icon",p:"Keep the name, <b>The Long Voyage</b>, and tap <b>Add</b>. If your phone asks again, tap <b>Add</b> once more.",
      fx:fnFx(`<div class="ui dl da"><b class=dt>Add to Home screen</b><div class=di>${fnApp()}<span class=fld>The Long Voyage</span></div><div class=bt><span>Cancel</span><span class="ok hl">Add${fnN(1)}</span></div></div>`)});
  else L.push({k:where,t:"Add the icon",p:"In this browser:",steps:a2Steps(k)});
  L.push(last);
  return FN.cards=L;
}
function fnCard(n){
  const L=fnCards();n=Math.min(Math.max(0,n),L.length-1);FN.n=n;
  const c=L[n],last=n===L.length-1;
  bar("THE LONG VOYAGE",n?"HOME SCREEN":"WELCOME");
  let o=`<section class="kick tut fn" aria-labelledby=th aria-roledescription="setup card"><div class="lab fnl"><span>${n?`Step ${pad(n)}/${pad(L.length-1)}`:"Before you start"}</span><span>${c.k}</span></div>`;
  o+=`<ol class=tsteps aria-hidden=true>${L.map((_,i)=>`<li class="${i<n?"d":i===n?"c":""}"></li>`).join("")}</ol>`;
  o+=`<h1 id=th tabindex=-1>${n?`<span class=sr>Step ${n} of ${L.length-1}: </span>`:""}${c.t}</h1><p class=lead>${c.p}</p>${c.steps||""}${c.fx?c.fx.replace("<div class=fig>",'<div class=fig aria-hidden=true>'):""}`;
  if(c.li)o+=`<ul class=bl>${c.li.map(([a,b])=>`<li><b>${a}</b><span>${b}</span></li>`).join("")}</ul>`;
  if(c.fine)o+=`<p class=fine>${c.fine}</p>`;
  if(!last)o+=`<p class=fnx><button data-fn=here>Play in this browser this time</button></p>`;
  $("v").innerHTML=o+"</section>";
  dock(n?`<div class=tnav><button class="btn sec" data-fn=back aria-label="Previous step"><span>Back</span></button>${last
    ?`<button class="btn sec" data-fn=here><span>Play here</span></button>`
    :`<button class="btn pri" data-fn=next><span>Next</span><i>${pad(n+1)}/${pad(L.length-1)}</i></button>`}</div>`
    :`<button class="btn pri" data-fn=next><span>Add the icon</span><i>${L.length-1} steps</i></button>`,"");
  fnFocus();
}
function fnOpen(){
  const ios=!fnAnd();
  bar("THE LONG VOYAGE","HOME SCREEN");
  $("v").innerHTML=`<section class="kick fn" aria-labelledby=th><div class="lab fnl"><span>On this phone</span><span>Icon added</span></div>`+
    `<h1 id=th tabindex=-1>You have the icon</h1><p class=lead>This phone has opened the game from <b>The Long Voyage</b> on its home screen. Play from there: it opens ${ios?"full screen, like an app":`in one tap, and ${A2_FS} makes it full screen`}.</p>`+
    `${fxHome()}<p class=fine>${A2_WIFI}</p><p class=fnx><button data-fn=add>No icon on this phone? Show me how to add it</button></p></section>`;
  dock(`<button class="btn sec" data-fn=play><span>Play here anyway</span><i>this time</i></button>`,"");
  fnFocus();
}
function fnLeave(known){
  const ios=FN.k==="sheet",app=ios?"Safari":"Chrome",at=`<b class="a2u m">${fnAd()}</b>`;
  const out=ios?"Tap <b>Cancel</b> at the top, then <b>Use Without Internet</b>. You stay on the ship's Wi-Fi."
    :"Close this screen. If your phone asks, stay connected: the ship's Wi-Fi has no internet, and that's fine.";
  const steps=known?[out,`Tap <b>The Long Voyage</b> on your home screen. No icon there? Open <b>${app}</b> and go to ${at}`]:[out,`Open <b>${app}</b> and go to ${at}`];
  bar("THE LONG VOYAGE","SHIP'S WI-FI");
  $("v").innerHTML=`<section class="kick fn" aria-labelledby=th><div class="lab fnl"><span>Connected to the ship</span><span>${steps.length} steps</span></div>`+
    `<h1 id=th tabindex=-1>${known?"Open the game from your icon":"Open the game in "+app}</h1>`+
    `<p class=lead>${known?"This phone already has <b>The Long Voyage</b> on its home screen. This window is only for joining Wi-Fi.":`This window is only for joining Wi-Fi: it can't keep the game. In ${app}, the game goes on your home screen, one tap away.`}</p>`+
    `<ol class=a2s>${steps.map((s,i)=>`<li><b class=m>${pad(i+1)}</b><span>${s}</span></li>`).join("")}</ol>`+
    (ios?fnFx(`<div class="ui cn"><span>Log In</span><b>${fnAd()}</b><span class=hl>Cancel${fnN(1)}</span></div><div class="ui as"><div class="r hl">Use Without Internet${fnN(2)}</div><div class=r>Use Other Network</div></div>`)
      :fnFx(`<div class="ui cn"><span class=hl>${FX.x}${fnN(1)}</span><b>Sign in to Wi-Fi network</b><span></span></div>`))+`</section>`;
  dock("","");
  fnFocus();
}
document.addEventListener("click",(ev)=>{
  const el=ev.target.closest("button[data-fn]");if(!el)return;
  const a=el.dataset.fn;FN.tap=true;
  if(a==="next")return fnCard(FN.n+1);
  if(a==="back")return fnCard(FN.n-1);
  if(a==="add")return fnShow("ADD",1);
  if(a==="here"||a==="play"){fnSS("lv.here","1");fnShow("GAME")}
});
// Back from the home screen with the icon added and opened: this tab says so.
document.addEventListener("visibilitychange",async()=>{
  if(FN.scr!=="ADD"||document.visibilityState!=="visible")return;
  const r=await fnHello(false);
  if(FN.scr==="ADD"&&r&&r.installed)fnShow("OPEN");
});
// Settings' home-screen steps on Android: the address carries the icon's marker there too.
const view_fn=view;view=function(){
  view_fn();
  if(fnAnd()&&!a2Std()){const on=route==="set";if(on)fnSS("lv.fnadd","1");fnMark(on)}
};

// The game on the phone's home screen (web/a2hs.css; docs/OTA.md "On the home screen").
// The page is plain http on the ship's own address, so browsers won't offer a one-tap
// install (that needs HTTPS and a service worker). What they do allow by hand: iOS Safari
// (Share > Add to Home Screen) opens it full screen like an app; Android Chrome
// (menu > Add to Home screen) makes a shortcut that opens a Chrome tab. This shows how,
// once, on the home screen (and any time in Settings: web/settings.js), worded for the browser
// you're in. The captive sign-in windows can't add icons, so there it says how to get to
// a real browser first. Not shown once the game runs from the icon.
const A2K="lv.a2hs";
let A2_OFF=false;   // dismissed this visit (the captive sheets forget localStorage)
function a2Std(){try{return navigator.standalone===true||["standalone","fullscreen","minimal-ui"].some((m)=>matchMedia(`(display-mode: ${m})`).matches)}catch(e){return false}}
// "" (nothing to offer), ios (Safari), iosx (Chrome/Firefox/Edge on iOS), sheet (iOS
// captive window), and (Chrome), sam (Samsung Internet), awv (Android sign-in window).
function a2Kind(){
  if(a2Std())return "";
  const u=navigator.userAgent;
  if(/iPhone|iPad|iPod/.test(u)||(/Macintosh/.test(u)&&navigator.maxTouchPoints>1))return /CriOS|FxiOS|EdgiOS/.test(u)?"iosx":/Safari\//.test(u)?"ios":"sheet";
  if(/Android/.test(u))return /; wv\)/.test(u)?"awv":/SamsungBrowser/.test(u)?"sam":/Chrome\//.test(u)?"and":"";
  return "";
}
function a2Done(){if(A2_OFF)return true;try{return localStorage.getItem(A2K)==="1"}catch(e){return false}}
const A2_SH=`<svg class=a2i viewBox="0 0 16 16" aria-label=Share role=img><path d="M8 1.5v8.5M5 4.5l3-3 3 3M5.5 7H3v7.5h10V7h-2.5"/></svg>`;
const A2_MV=`<svg class=a2i viewBox="0 0 16 16" aria-label=menu role=img><circle cx=8 cy=3 r=1.4 /><circle cx=8 cy=8 r=1.4 /><circle cx=8 cy=13 r=1.4 /></svg>`;
// Safari's page menu (iOS 18+): a box over two lines, at the left of the address bar.
const A2_PM=`<svg class=a2i viewBox="0 0 16 16" aria-label="page menu" role=img><path d="M2.5 2.5h11v5h-11zM2.5 10.5h11M2.5 13.5h7"/></svg>`;
const A2_MH=`<svg class=a2i viewBox="0 0 16 16" aria-label=More role=img><circle cx=3 cy=8 r=1.4 /><circle cx=8 cy=8 r=1.4 /><circle cx=13 cy=8 r=1.4 /></svg>`;
// The share sheet's View More button (a chevron in a circle; iOS 26).
const A2_VM=`<svg class=a2i viewBox="0 0 16 16" aria-label="View More" role=img><path d="M3.5 6l4.5 4.5 4.5-4.5"/></svg>`;
function a2Steps(k){
  const u=navigator.userAgent,v=+((u.match(/Version\/(\d+)/)||[])[1]||0),pad_=/iPad|Macintosh/.test(u);
  const at=`<b class="a2u m">${h(location.host||"192.168.4.1")}</b>`;
  const add="Tap <b>Add to Home Screen</b>, then <b>Add</b>.";
  // Safari 26 (app.html tells it by anchor positioning too: its user agent says 18_6).
  const i26=v>=26||!!(window.CSS&&CSS.supports("anchor-name:--a"));
  const S_={
    // iOS 26, as on a real iPhone: the page menu at the left of the address bar has Share
    // first; the share sheet hides Add to Home Screen under View More. In the Bottom and
    // Top tab layouts Share is also a toolbar button, hence the second sentence.
    ios:i26?[`Tap ${A2_PM} in the address bar, then <b>Share</b> ${A2_SH}. Share in Safari's toolbar? Tap that.`,
      `Tap <b>View More</b> ${A2_VM}, then <b>Add to Home Screen</b>.`,
      "Keep <b>Open as Web App</b> on, then tap <b>Add</b>."]:
      [`Tap <b>Share</b> ${A2_SH} at the ${pad_?"top":"bottom"} of Safari.`,"Scroll down. "+add],
    iosx:[`Tap <b>Share</b> ${A2_SH}: it's in the address bar or the browser's menu.`,"Scroll down. "+add],
    sheet:["This sign-in window can't add icons. Tap <b>Cancel</b> at the top, then <b>Use Without Internet</b>. You stay on the ship's Wi-Fi.",
      `Open <b>Safari</b> and go to ${at}`,i26?`Tap ${A2_PM} in the address bar, then <b>Share</b>, <b>View More</b> ${A2_VM} and <b>Add to Home Screen</b>.`:`Tap <b>Share</b> ${A2_SH}, then <b>Add to Home Screen</b>.`],
    and:[`Tap ${A2_MV} at the top right of Chrome.`,"Tap <b>Add to Home screen</b>, then <b>Add</b>."],
    sam:["Tap <b>☰</b> at the bottom of the screen.","Tap <b>Add page to</b>, then <b>Home screen</b>."],
    awv:["This sign-in screen can't add icons. Close it. Your phone stays on the ship's Wi-Fi.",
      `Open <b>Chrome</b> and go to ${at}`,`Tap ${A2_MV}, then <b>Add to Home screen</b>.`]};
  return `<ol class=a2s>${S_[k].map((s,i)=>`<li><b class=m>${pad(i+1)}</b><span>${s}</span></li>`).join("")}</ol>`;
}
function a2Opens(k){return /^(ios|iosx|sheet)$/.test(k)?"full screen, like an app":"in a Chrome tab"}
const A2_WIFI="The icon only works while your phone is on the ship's Wi-Fi. Anywhere else it opens to a can't-connect page.";
const home_a2=home;home=function(){
  home_a2();
  const k=a2Kind(),top=document.querySelector("#v>.kick");
  // One thing at a time: an update notice wins this visit.
  if(!k||a2Done()||!top||S.ending!==NONE||document.querySelector("#v .otab"))return;
  top.insertAdjacentHTML("afterend",`<section class=a2h aria-labelledby=a2t><div class=lab><span id=a2t>Home screen</span><span>${a2Steps(k).split("<li>").length-1} steps</span></div><p class=a2l>Keep the game one tap away. It opens ${a2Opens(k)}.</p>${a2Steps(k)}<p class=fine>${A2_WIFI}</p><div class=a2b><button class="btn sec" data-a2h=ok><span>Got it</span><i>hide this</i></button></div></section>`);
};
document.addEventListener("click",(ev)=>{
  const el=ev.target.closest("button[data-a2h]");if(!el)return;
  A2_OFF=true;try{localStorage.setItem(A2K,"1")}catch(e){}
  el.closest(".a2h")?.remove();
});

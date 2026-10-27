// Full screen on Android (web/fullscreen.css; docs/OTA.md section 6). The page stays plain
// http, so Android Chrome's home-screen icon is a shortcut that opens a Chrome tab, address
// bar and all. What http still allows is the Fullscreen API, from a tap: a small button in
// the top bar, beside the gear, that hides once the page is full screen (the fullscreenchange
// event, and :fullscreen in the CSS) and comes back when Back or a swipe leaves it. Chrome
// forgets full screen when the page reloads, so it's one tap each time the game opens. Only
// on Android browsers that have the API (not the sign-in window, a WebView without it); never
// on iOS, whose icon already opens full screen. If the request is refused, nothing happens.
const FS_I=`<svg viewBox="0 0 20 20" aria-hidden=true><path d="M3 7.5V3h4.5M12.5 3H17v4.5M17 12.5V17h-4.5M7.5 17H3v-4.5"/></svg>`;
function fsCan(){
  const d=document.documentElement,u=navigator.userAgent;
  return /Android/.test(u)&&!/; wv\)/.test(u)&&!!(document.fullscreenEnabled&&d.requestFullscreen);
}
function fsOn(){return !!document.fullscreenElement}
const shipTop_fs=shipTop;shipTop=function(){
  shipTop_fs();
  const s=$("top")&&$("top").querySelector("span");if(!s||!fsCan())return;
  const b=`<button class=fsb data-fs=1 aria-label="Full screen"${fsOn()?" hidden":""}>${FS_I}</button>`;
  const g=s.querySelector(".gear");g?g.insertAdjacentHTML("beforebegin",b):s.insertAdjacentHTML("beforeend",b);
};
document.addEventListener("click",(ev)=>{
  if(!ev.target.closest("button[data-fs]"))return;
  try{const r=document.documentElement.requestFullscreen({navigationUI:"hide"});if(r&&r.catch)r.catch(()=>{})}catch(e){}
});
document.addEventListener("fullscreenchange",()=>{for(const b of document.querySelectorAll(".fsb"))b.hidden=fsOn()});

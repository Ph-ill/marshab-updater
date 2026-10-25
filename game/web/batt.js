// The ship's battery (board/lvbatt.py, a UPS-Lite on the Pico W; docs/BATTERY.md). S.bat from
// /api/state is [percent, mV, charging] or null on a board without one: then none of this
// shows. Kept in its own file and hooked onto app.html's shipTop/home/TUT from here, so
// app.html carries only the two placeholders build.py fills.
const BAT_LOW=15;
function batIcon(b){
  const p=b[0],low=p!=null&&p<BAT_LOW&&!b[2],w=p==null?0:Math.max(1,Math.round(Math.min(100,p)*14/100));
  return `<svg class=bati viewBox="0 0 22 12" aria-hidden=true><rect x=".5" y=".5" width="18" height="11" rx="1.5" fill=none stroke=currentColor /><rect x="19" y="3.5" width="2.5" height="5" fill=currentColor /><rect x="2.5" y="2.5" width="${w}" height="7" fill="${low?"var(--rust)":"currentColor"}"/>${b[2]?`<path d="M10.5 1.5 6.5 6.5h3l-1 4 4-5h-3Z" fill="var(--paper)" stroke=currentColor stroke-width=".8" stroke-linejoin=round />`:""}</svg>`;
}
function batTop(){
  const b=S&&S.bat,t=$("top");if(!b||!t)return;
  const s=t.querySelector("span");if(!s)return;
  const p=b[0],low=p!=null&&p<BAT_LOW&&!b[2];
  s.insertAdjacentHTML("afterbegin",`<span class="bat${low?" low":""}" role=img aria-label="Ship battery ${p==null?"reading unavailable":p+"%"}${b[2]?", charging":""}">${batIcon(b)}${p==null?"--":p}%</span>`);
}
const shipTop0=shipTop;shipTop=function(){shipTop0();batTop()};
const home0=home;home=function(){
  home0();
  const b=S&&S.bat;
  if(b&&S.ending===NONE&&b[0]!=null&&b[0]<BAT_LOW&&!b[2])$("v").insertAdjacentHTML("afterbegin",`<p class=batlow role=status><b>Battery ${b[0]}%</b> · Plug your ship in when you can. Its USB cable charges it while you play.</p>`);
};
const TUT0=TUT;TUT=function(){
  const L=TUT0();
  if(S&&S.bat){const c=L.find((x)=>x[0]==="How it works")||L[1];if(c)c[4].push(["Battery","This ship runs on its own battery. The charge shows at the top of the screen; plug its USB cable in when it runs low."])}
  return L;
};

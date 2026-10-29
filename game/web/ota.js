// Over-the-air updates, the phone's side (the ship's: board/lvota.py; docs/OTA.md). The ship
// has no internet, so this page fetches the release: the newest signed release on the
// ship's channel, from the public repo on GitHub, whenever this phone can reach it (on mobile
// data or other Wi-Fi; on the ship's hotspot it usually can't, and fails quietly). The
// release waits in this browser's storage until you're back on the ship's Wi-Fi, then a
// notice on the home screen offers to install it, and Settings › Ship software (web/settings.js)
// shows what runs and what's available. Installing sends it to the ship in small pieces; the ship checks the
// signature and every file, restarts into it and goes back by itself if it doesn't start.
// Hooked onto app.html's refresh/home from here, like batt.js; settings.js shows the screens.
const OTA_SRC="https://raw.githubusercontent.com/Ph-ill/marshab-updater/main";
const OTA_KEY="lv.ota",OTA_EVERY=6*3600e3,OTA_RETRY=120e3,OTA_WAIT=8000;
let OS_=null,OB=null,OI=null,OTA_LATER="",OTA_BUSY=false,OTA_NONE=false;  // ship's status, update here, install progress; a ship without OTA
function otaLoad(){try{return JSON.parse(localStorage.getItem(OTA_KEY))||{}}catch(e){return{}}}
function otaSave(o){try{localStorage.setItem(OTA_KEY,JSON.stringify(o));return true}catch(e){return false}}
function vcmp(a,b){
  const p=(v)=>{const [c,...r]=String(v||"").replace(/^v/i,"").split("-");const n=c.split(".").map((x)=>parseInt(x,10)||0);while(n.length<3)n.push(0);return{n,pre:r.join("-")}};
  const x=p(a),y=p(b);for(let i=0;i<3;i++)if(x.n[i]!==y.n[i])return x.n[i]-y.n[i];
  return x.pre===y.pre?0:!x.pre?1:!y.pre?-1:x.pre<y.pre?-1:1;
}
async function otaGet(url){
  const c=new AbortController(),t=setTimeout(()=>c.abort(),OTA_WAIT);
  try{const r=await fetch(url,{cache:"no-store",signal:c.signal});if(!r.ok)throw new Error(r.status);return await r.json()}finally{clearTimeout(t)}
}
// The update this ship can take, if this phone has one: same channel, same frozen core, newer.
function otaFor(st){
  const b=OB||otaLoad();if(!st||!b.rel)return null;
  const r=b.rel;return r.ch===st.ch&&r.core===st.core&&vcmp(r.v,st.v)>0?r:null;
}
async function otaStatus(){
  try{const r=await fetch("/api/ota",{cache:"no-store"});if(r.status===404)OTA_NONE=true;OS_=r.ok?await r.json():null}catch(e){if(e instanceof SyntaxError)OTA_NONE=true}
  if(OS_&&OS_.ch){const b=otaLoad();if(b.ch!==OS_.ch||b.core!==OS_.core){b.ch=OS_.ch;b.core=OS_.core;otaSave(b);OB=b}}
  return OS_;
}
// Look on GitHub. Quiet unless asked (force): a phone on the ship's hotspot has no internet.
async function otaCheck(force){
  const b=otaLoad();OB=b;
  if(!b.ch||OTA_BUSY)return;
  if(!force&&b.at&&Date.now()-b.at<(b.ok?OTA_EVERY:OTA_RETRY))return;
  b.at=Date.now();b.ok=false;otaSave(b);
  try{
    const idx=await otaGet(OTA_SRC+"/firmware/index.json");
    const v=(idx.channels||{})[b.ch],e=(idx.releases||[]).find((r)=>r.version===v);
    b.ok=true;b.seen=v||null;
    if(e&&e.ota&&e.frozen===b.core&&(!b.rel||b.rel.v!==v)){
      const rel=await otaGet(OTA_SRC+e.path),env=rel.ota;
      const m=JSON.parse(env.m),by={};for(const f of rel.files)by[f.path]=f.data;
      if(m.version!==v||m.files.some((f)=>!by[f[0]]))throw new Error("incomplete release");
      b.rel={v,ch:m.channel,core:m.core,label:rel.label||"",bytes:m.files.reduce((s,f)=>s+f[1],0),env:JSON.stringify(env),files:m.files.map((f)=>by[f[0]])};
    }
    b.err="";
  }catch(e){b.ok=false;b.err=e.name==="AbortError"||e instanceof TypeError?"offline":"failed"}
  b.at=Date.now();
  if(!otaSave(b)){b.rel=null;b.err="full";otaSave(b)}
  OB=b;
  if(route==="set"||route==="home")view();
}
// ---- installing: the signed envelope, then each file, in pieces the ship takes (chunk) ----
async function otaPut(q,body){
  for(let i=0;;i++){
    try{
      const r=await fetch("/api/ota/put?"+q,{method:"POST",body,headers:{"X-Crew-Token":tok,"Content-Type":"application/octet-stream"}});
      const j=await r.json().catch(()=>({}));
      if(r.status===401)throw Object.assign(new Error("Sign in again, then install."),{stop:1});
      if(r.status===503&&i<4){await new Promise((ok)=>setTimeout(ok,800*(i+1)));continue}
      return[r.status,j];
    }catch(e){if(e.stop||i>=4)throw e;await new Promise((ok)=>setTimeout(ok,800*(i+1)))}
  }
}
async function otaSend(f,bytes,n,extra){
  let o=0;
  while(o<bytes.length||(!bytes.length&&o===0)){
    const [s,j]=await otaPut(`f=${f}${extra}&o=${o}`,bytes.subarray(o,o+n));
    if(s===409&&j.have!=null){o=j.have;continue}
    if(s!==200)throw Object.assign(new Error(j.err||"The ship turned the update down."),{status:s});
    o=j.have!=null?j.have:o+n;OI.done+=0;otaProg(f,o);
    if(j.done||!bytes.length)break;
  }
}
function otaProg(f,o){if(!OI)return;OI.f=f;OI.o=o;const el=$("otap");if(el)el.outerHTML=otaBar()}
function otaBar(){
  const I=OI,sz=I.sizes,tot=sz.reduce((a,b)=>a+b,0)||1;
  let got=0;for(let i=0;i<sz.length;i++)got+=i+1<I.f?sz[i]:i+1===I.f?Math.min(I.o,sz[i]):0;
  const pc=I.step==="send"?Math.round(got*100/tot):I.step==="env"?0:100;
  return `<div id=otap><div class=otabar role=progressbar aria-valuemin=0 aria-valuemax=100 aria-valuenow=${pc}><i style="width:${pc}%"></i></div><p class=fine>${I.step==="env"?"Sending the signature":I.step==="send"?`File ${I.f} of ${sz.length} · ${Math.round(got/1024)} of ${Math.round(tot/1024)} KB`:I.step==="wait"?"Waiting for your ship to come back":"Done"}</p></div>`;
}
// SHA-256 of bytes, as hex: the page is served over plain http from the ship, where
// crypto.subtle isn't available. Only used on the envelope (a few KB), once per install.
function otaSha(b){
  const K=[],H=[],r=(x,n)=>x>>>n|x<<32-n;
  for(let c=2,k=0;k<64;c++){let p=1;for(let d=2;d*d<=c;d++)if(c%d==0){p=0;break}if(p){if(k<8)H[k]=Math.pow(c,1/2)*2**32|0;K[k++]=Math.pow(c,1/3)*2**32|0}}
  const l=b.length,n=((l+9+63)>>6)<<6,m=new Uint8Array(n);m.set(b);m[l]=128;
  const dv=new DataView(m.buffer);dv.setUint32(n-4,l*8>>>0);dv.setUint32(n-8,Math.floor(l/2**29));
  const w=new Array(64);
  for(let o=0;o<n;o+=64){
    let [a,bb,c,d,e,f,g,h]=H;
    for(let i=0;i<64;i++){
      if(i<16)w[i]=dv.getUint32(o+4*i);
      else w[i]=(r(w[i-15],7)^r(w[i-15],18)^w[i-15]>>>3)+w[i-7]+(r(w[i-2],17)^r(w[i-2],19)^w[i-2]>>>10)+w[i-16]|0;
      const t1=h+(r(e,6)^r(e,11)^r(e,25))+(e&f^~e&g)+K[i]+w[i]|0,t2=(r(a,2)^r(a,13)^r(a,22))+(a&bb^a&c^bb&c)|0;
      h=g;g=f;f=e;e=d+t1|0;d=c;c=bb;bb=a;a=t1+t2|0;
    }
    [a,bb,c,d,e,f,g,h].forEach((v,i)=>H[i]=H[i]+v|0);
  }
  return H.map((v)=>(v>>>0).toString(16).padStart(8,"0")).join("");
}
async function otaCancel(){try{await fetch("/api/ota/cancel",{method:"POST",headers:{"X-Crew-Token":tok}})}catch(e){}}
async function otaInstall(){
  const r=otaFor(OS_);if(!r||OTA_BUSY)return;
  OTA_BUSY=true;OI={v:r.v,prev:OS_.v,step:"env",f:0,o:0,sizes:JSON.parse(JSON.parse(r.env).m).files.map((f)=>f[1]),msg:""};
  go("set");view();
  try{
    const st=await otaStatus();if(!st)throw new Error("Your ship didn't answer. Stay close and try again.");
    const n=st.chunk||1024,enc=new TextEncoder(),env=enc.encode(r.env);
    // Carry on from what the ship already has only if it staged this very envelope (the
    // same bytes, by hash: a version signed twice never mixes). Anything else staged is
    // cancelled first and the upload starts again from nothing.
    let have=st.staged&&st.staged.v===r.v&&st.staged.h&&st.staged.h===otaSha(env)?st.staged.have:null;
    if(st.staged&&!have)await otaCancel();
    for(let k=0;;k++){
      try{
        if(!have){OI.step="env";view();await otaSend(0,env,n,`&n=${env.length}`)}
        OI.step="send";view();
        for(let i=0;i<r.files.length;i++){
          if(have&&have[i]===OI.sizes[i])continue;
          const b=Uint8Array.from(atob(r.files[i]),(c)=>c.charCodeAt(0));
          await otaSend(i+1,b,n,"");
        }
        break;
      }catch(e){
        // A checksum the ship turned down while carrying on: what it kept isn't this
        // update's. Cancel and send the whole thing once more, from the signature.
        if(!have||e.status!==400||k)throw e;
        await otaCancel();have=null;
      }
    }
    const a=await fetch("/api/ota/apply",{method:"POST",headers:{"X-Crew-Token":tok}}),j=await a.json().catch(()=>({}));
    if(!a.ok)throw new Error(j.err||"Your ship wouldn't start the update.");
    OI.step="wait";view();
    await new Promise((ok)=>setTimeout(ok,(j.restart_ms||1500)+4000));
    const t0=Date.now();let back=null;
    while(Date.now()-t0<150e3){
      try{const c=new AbortController(),tt=setTimeout(()=>c.abort(),3000);const q=await fetch("/api/ota",{cache:"no-store",signal:c.signal});clearTimeout(tt);if(q.ok){back=await q.json();break}}catch(e){}
      await new Promise((ok)=>setTimeout(ok,2500));
    }
    OS_=back;
    OI.step="done";OI.ok=back&&back.v===r.v;
    OI.msg=!back?"Your ship hasn't come back on this phone's Wi-Fi yet. Rejoin its network, then reload this page.":OI.ok?"":back.last&&back.last.result==="rolled back"?`It didn't start, so your ship went back to ${back.v}.`:`Your ship still runs ${back.v}.`;
  }catch(e){OI.step="done";OI.ok=false;OI.msg=e.message||"That didn't work. Try again."}
  OTA_BUSY=false;view();
}
// ---- what you see ---------------------------------------------------------------------
// An update that already went back on this ship isn't pushed again (the screen still offers it).
function otaNag(){const r=otaFor(OS_),l=OS_&&OS_.last;return r&&!(l&&l.result==="rolled back"&&l.v===r.v)?r:null}
function otaAgo(t){if(!t)return"never";const m=(Date.now()-t)/6e4|0;return m<1?"just now":m<60?m+" min ago":m<1440?(m/60|0)+" h ago":(m/1440|0)+" d ago"}
// While installing (and its outcome): Settings shows only this (settings.js).
function otaScreen(){
  shipTop();
  const I=OI;
  let o=`<div class=kick><div class=lab>Settings</div><h1>Ship software</h1></div><section><div class=lab><span>${I.step==="done"?I.ok?"Installed":"Not installed":"Installing"}</span><span class=m>${h(I.v)}</span></div>`;
  if(I.step!=="done")o+=otaBar()+`<p class=dim>Keep this screen open and stay close to your ship. It restarts at the end, so the game drops for about half a minute.</p>`;
  else o+=I.ok?`<p class=lead>Your ship runs ${h(I.v)} now.</p><p class=dim>It restarted, so sign in again to carry on. Your crew, log and votes are kept on the ship.</p>`:`<p class=lead>${h(I.msg)}</p><p class=dim>Your crew, log and votes are kept on the ship either way.</p>`;
  $("v").innerHTML=o+`</section>`;
  dock(I.step!=="done"?`<button class="btn sec" disabled><span>Installing</span><i>${I.step==="wait"?"restarting":"sending"}</i></button>`:I.ok||!OS_?`<button class="btn pri" data-ota=reload><span>Back aboard</span><i>reload</i></button>`:`<button class="btn sec" data-ota=clear><span>Back</span><i>←</i></button>`,"set");
}
// What the Available row says. Only the latest check counts: when it failed (no internet on
// the ship's hotspot, say), an older look is no answer, so it never claims "Up to date".
// An update already on this phone is shown either way.
function otaChecking(b){return b.at&&Date.now()-b.at<OTA_WAIT+2000&&!b.ok&&!b.err}
function otaAvail(st,b,r){
  if(r)return h(r.v);
  if(otaChecking(b))return "Checking";
  if(b.at&&!b.ok)return "Couldn't check";
  return b.seen&&st&&vcmp(b.seen,st.v)<=0?"Up to date":b.seen?h(b.seen)+" (not signed for this ship)":"—";
}
// Settings' Ship software section: what runs, what's ready, Install and Check for updates.
function otaSect(){
  const st=OS_,b=OB||otaLoad(),r=otaFor(st),last=st&&st.last;
  let o=`<section id=set-sw><div class=lab><span>Ship software</span>${otaNag()?`<span class=otan><i>update ready</i></span>`:""}</div><dl class="facts otaf"><dt>Installed</dt><dd class=m>${st?h(st.v||"unknown"):"—"}</dd><dt>Channel</dt><dd>${st?h(st.ch||"—"):"—"}</dd><dt>Available</dt><dd class=m>${otaAvail(st,b,r)}</dd><dt>Checked</dt><dd>${otaAgo(b.at)}${b.at&&!b.ok?" · no internet":""}</dd></dl>`;
  if(last&&last.result==="rolled back")o+=`<p class=upd><b>Went back</b> · ${h(last.v)} didn't start, so your ship returned to ${h(last.prev)}.</p>`;
  else if(last&&last.result==="installed"&&last.v===(st&&st.v))o+=`<p class=fine>${h(last.v)} installed over the air.</p>`;
  if(!st)o+=`<p class=dim>Your ship can't take updates over the air yet. It needs one install over USB first.</p>`;
  else if(r)o+=`<p>${h(r.v)} is on this phone, ready for your ship. ${Math.round(r.bytes/1024)} KB, about a minute to send.</p><p class=dim>Your ship checks the signature and every file before it switches over, and goes back by itself if the new version doesn't start. Your crew, log and votes stay as they are.</p>`;
  else o+=`<p class=dim>This phone looks for updates on the internet. On your ship's Wi-Fi it usually can't, so if the check fails, try again on mobile data or another network and come back. Whatever it finds waits on this phone.</p>`;
  if(st)o+=`<div class=otas>${r?`<button class="btn pri" data-ota=install><span>${otaNag()?"Install":"Try again:"} ${h(r.v)}</span><i>${Math.round(r.bytes/1024)} KB</i></button>`:""}<button class="btn sec" data-ota=check><span>Check for updates</span><i>${otaChecking(b)?"checking":"github"}</i></button></div>`;
  return o+`</section>`;
}
const home_o=home;home=function(){
  home_o();
  const r=otaNag();
  if(!r||OTA_LATER===r.v||OTA_BUSY||S.ending!==NONE)return;
  $("v").insertAdjacentHTML("afterbegin",`<div class=otab role=status><p><b>Update ready</b> · Ship software ${h(r.v)} is on this phone. Install it now? Your ship restarts for about half a minute. It's in Settings too.</p><div><button class="btn pri" data-ota=install><span>Install</span><i>${Math.round(r.bytes/1024)} KB</i></button><button class="btn sec" data-ota=later><span>Later</span></button></div></div>`);
};
const refresh_o=refresh;refresh=async function(){
  await refresh_o();
  if(!OS_&&!OTA_NONE&&!OTA_BUSY){await otaStatus();if(OS_){if(route==="home"||route==="set")view();otaCheck(false)}}
};
document.addEventListener("click",(ev)=>{
  const el=ev.target.closest("button[data-ota]");if(!el||el.disabled)return;
  const k=el.dataset.ota;
  if(k==="install")return otaInstall();
  if(k==="later"){OTA_LATER=(otaFor(OS_)||{}).v||"";return view()}
  if(k==="check"){el.disabled=true;el.querySelector("i").textContent="checking";return otaCheck(true).then(()=>otaStatus()).then(view)}
  if(k==="reload")return location.reload();
  if(k==="clear"){OI=null;return view()}
});
// Internet back (left the hotspot, or the phone found another route): look again.
addEventListener("online",()=>otaCheck(false));
document.addEventListener("visibilitychange",()=>{if(!document.hidden)otaCheck(false)});

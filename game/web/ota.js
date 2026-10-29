// Over-the-air updates, the phone's side (the ship's: board/lvota.py; docs/OTA.md). The ship
// has no internet, so this page fetches the release: the newest signed release on the
// ship's channel, from the public repo on GitHub, whenever this phone can reach it (on mobile
// data or other Wi-Fi; on the ship's hotspot it usually can't, and fails quietly). The
// release waits in this browser's storage until you're back on the ship's Wi-Fi, then a
// notice on the home screen offers to install it, and Settings › Ship software (web/settings.js)
// shows what runs and what's available. Installing sends it to the ship in small pieces; the ship checks the
// signature and every file, restarts into it and goes back by itself if it doesn't start.
// Hooked onto app.html's refresh/home from here, like batt.js; settings.js shows the screens.
// Releases come from the repo's main branch, unless the ship names another (its ship.json
// "ota_src", in /api/ota's "src": a test ship on a test branch). A branch name only.
const OTA_REPO="https://raw.githubusercontent.com/Ph-ill/marshab-updater/";
function otaSrc(b){const s=b&&b.src;return OTA_REPO+(typeof s==="string"&&/^[\w][\w.\/-]{0,63}$/.test(s)&&s.indexOf("..")<0?s:"main")}
// What's new (0.3.0): each release's few plain lines (game/tools/ota/whatsnew.json) show with
// an update that's ready in Settings, and Version history lists them all; see otaHist below.
const OTA_KEY="lv.ota",OTA_EVERY=6*3600e3,OTA_RETRY=120e3,OTA_WAIT=8000,OTA_BODY_WAIT=30000,OTA_AGAIN=1500;
let OS_=null,OB=null,OI=null,OTA_LATER="",OTA_BUSY=false,OTA_NONE=false;  // ship's status, update here, install progress; a ship without OTA
let OTA_CHECK=false;  // one check, including its delayed retry; never inferred from a timestamp
let OH=null;    // Version history, while it's open: {st: "load" | "on" | "off", list, mine}
function otaLoad(){try{return JSON.parse(localStorage.getItem(OTA_KEY))||{}}catch(e){return{}}}
function otaSave(o){try{localStorage.setItem(OTA_KEY,JSON.stringify(o));return true}catch(e){return false}}
function vcmp(a,b){
  const p=(v)=>{const [c,...r]=String(v||"").replace(/^v/i,"").split("-");const n=c.split(".").map((x)=>parseInt(x,10)||0);while(n.length<3)n.push(0);return{n,pre:r.join("-")}};
  const x=p(a),y=p(b);for(let i=0;i<3;i++)if(x.n[i]!==y.n[i])return x.n[i]-y.n[i];
  return x.pre===y.pre?0:!x.pre?1:!y.pre?-1:x.pre<y.pre?-1:1;
}
function otaErr(kind,status){return Object.assign(new Error(kind),{kind,status})}
async function otaGet(url,wait=OTA_WAIT){
  const c=new AbortController(),t=setTimeout(()=>c.abort(),wait);
  try{const r=await fetch(url,{cache:"no-store",signal:c.signal});if(!r.ok)throw otaErr("http",r.status);return await r.json()}
  catch(e){throw e.kind?e:otaErr(c.signal.aborted?"timeout":e instanceof TypeError?"network":"bad")}
  finally{clearTimeout(t)}
}
function otaNet(err){return err==="network"||err==="timeout"||err==="offline"}
// Check the envelope's shape, not its authenticity: only your ship verifies the signature.
function otaRelease(rel,v,b,e){
  const env=rel&&rel.ota;
  if(!env||typeof env.m!=="string"||typeof env.kid!=="string"||!env.kid||typeof env.sig!=="string"||!/^[A-Za-z0-9+/]{86}==$/.test(env.sig))throw otaErr("bad");
  const m=JSON.parse(env.m),by=Object.create(null);
  if(!m||m.schema!==1||m.project!=="LongVoyage"||m.version!==v||m.channel!==b.ch||m.core!==b.core||!Array.isArray(m.files)||!m.files.length||!Array.isArray(rel.files))throw otaErr("bad");
  for(const f of rel.files){if(!f||typeof f.path!=="string"||typeof f.data!=="string"||Object.prototype.hasOwnProperty.call(by,f.path))throw otaErr("bad");by[f.path]=f.data}
  const paths=new Set();
  for(const f of m.files){
    if(!Array.isArray(f)||typeof f[0]!=="string"||paths.has(f[0])||!Number.isSafeInteger(f[1])||f[1]<0||typeof f[2]!=="string"||!/^[a-f0-9]{64}$/.test(f[2])||!Object.prototype.hasOwnProperty.call(by,f[0]))throw otaErr("bad");
    paths.add(f[0]);
    const data=by[f[0]];
    if(data.length%4||!/^[A-Za-z0-9+/]*={0,2}$/.test(data)||atob(data).length!==f[1])throw otaErr("bad");
  }
  return{v,ch:m.channel,core:m.core,label:typeof rel.label==="string"?rel.label:"",notes:otaClean(e.notes),bytes:m.files.reduce((s,f)=>s+f[1],0),env:JSON.stringify(env),files:m.files.map((f)=>by[f[0]])};
}
// The update this ship can take, if this phone has one: same channel, same frozen core, newer.
function otaFor(st){
  const b=OB||otaLoad();if(!st||!b.rel)return null;
  const r=b.rel;return r.ch===st.ch&&r.core===st.core&&vcmp(r.v,st.v)>0?r:null;
}
async function otaStatus(){
  try{const r=await fetch("/api/ota",{cache:"no-store"});if(r.status===404)OTA_NONE=true;OS_=r.ok?await r.json():null}catch(e){if(e instanceof SyntaxError)OTA_NONE=true}
  if(OS_&&OS_.ch){const b=otaLoad();const src=OS_.src||null;if(b.ch!==OS_.ch||b.core!==OS_.core||(b.src||null)!==src){if((b.src||null)!==src){b.at=0;b.rel=null}b.ch=OS_.ch;b.core=OS_.core;b.src=src;otaSave(b);OB=b}}
  return OS_;
}
// Look on GitHub. Quiet unless asked (force): a phone on the ship's hotspot has no internet.
async function otaCheck(force){
  if(OTA_CHECK||OTA_BUSY)return;
  const b=otaLoad();OB=b;
  if(!b.ch)return;
  if(!force&&b.at&&Date.now()-b.at<(b.ok?OTA_EVERY:OTA_RETRY))return;
  const prev=b.rel;
  OTA_CHECK=true;b.at=Date.now();b.ok=false;b.err="";delete b.http;otaSave(b);
  if(route==="set"||route==="home")view();
  try{
    const base=otaSrc(b);
    for(let attempt=0;;attempt++){
      try{
        const idx=await otaGet(base+"/firmware/index.json");
        if(!idx||!idx.channels||typeof idx.channels!=="object"||Array.isArray(idx.channels)||!Array.isArray(idx.releases))throw otaErr("bad");
        const v=idx.channels[b.ch],e=idx.releases.find((r)=>r&&r.version===v);
        if(v!=null&&(typeof v!=="string"||!v||!e))throw otaErr("bad");
        if(e&&e.frozen===b.core&&vcmp(v,OS_&&OS_.v)>0&&!e.ota)throw otaErr("bad");
        if(e&&e.ota&&e.frozen===b.core&&(!b.rel||b.rel.v!==v)){
          if(typeof e.path!=="string"||!e.path.startsWith("/firmware/")||e.path.includes("..")||/[?#]/.test(e.path))throw otaErr("bad");
          b.rel=otaRelease(await otaGet(base+e.path,OTA_BODY_WAIT),v,b,e);
        }else if(e&&b.rel&&b.rel.v===v)b.rel={...b.rel,notes:otaClean(e.notes)};
        b.ok=true;b.seen=v||null;break;
      }catch(e){
        if(attempt||!otaNet(e.kind))throw e;
        await new Promise((ok)=>setTimeout(ok,OTA_AGAIN));
      }
    }
  }catch(e){b.ok=false;b.err=e.kind||"bad";if(e.kind==="http")b.http=e.status}

  b.at=Date.now();
  if(!otaSave(b)){b.rel=prev||null;b.ok=false;b.err="full";delete b.http;otaSave(b)}
  OB=b;OTA_CHECK=false;
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
    if(s!==200)throw Object.assign(new Error(otaWhy(s,j)),{status:s});
    o=j.have!=null?j.have:o+n;OI.done+=0;otaProg(f,o);
    if(j.done||!bytes.length)break;
  }
}
// What a refusal tells the person. 503 is "no memory for it just now" (already tried a few
// times by otaPut); a 409 "busy, ..." is the ship still checking its last update (on trial).
function otaWhy(s,j){
  if(s===503)return"Your ship is busy right now. Ask everyone else to turn Wi-Fi off for a few minutes, then tap Install again.";
  if(/^busy,/.test(j.err||""))return"Your ship is still checking its last update. Try again in a couple of minutes.";
  return j.err||"The ship turned the update down.";
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
  const r=otaFor(OS_);if(!r||OTA_BUSY||OTA_CHECK)return;
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
        // update's. Cancel and send the whole thing once more, from the signature. And a
        // file the ship refused for want of a checked signature (409, no have: its check
        // ran out of memory and nothing answered): send the signature again, once.
        if(k||!(e.status===409||have&&e.status===400))throw e;
        if(e.status===400)await otaCancel();
        have=null;
      }
    }
    const a=await fetch("/api/ota/apply",{method:"POST",headers:{"X-Crew-Token":tok}}),j=await a.json().catch(()=>({}));
    if(!a.ok)throw new Error(a.status===409&&/^busy,/.test(j.err||"")?otaWhy(409,j):j.err||"Your ship wouldn't start the update.");
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
// ---- what's new ----------------------------------------------------------------------
// A release's lines come from index.json's "notes" (online; tools/build_release.py writes them,
// game/tools/ota/whatsnew.py fills older entries) or, offline, from OTA_WN: whatsnew.json as
// web/build.py baked it into this page, which the ship serves from its own (signed) release.
// The ship itself never reads them: nothing on its update path holds notes (0.3.0, heap).
// Display text only: cleaned here (strings only, at most 3 lines of 160 characters) and
// always put on the page through h(), never as markup.
const OTA_WN=/*WHATSNEW*/{};
function otaClean(n){return Array.isArray(n)?n.filter((x)=>typeof x==="string"&&x.trim()).slice(0,3).map((x)=>x.trim().slice(0,160)):[]}
function otaNotes(n){n=otaClean(n);return n.length?`<ul class=otaw>${n.map((x)=>`<li>${h(x)}</li>`).join("")}</ul>`:""}
// Version history (Settings › Ship software › Version history): every release on this
// ship's channel that has notes, newest first, the one installed and the one ready marked.
// Online it reads index.json; offline (the usual case on the ship's own Wi-Fi) it shows the
// installed version's lines from this page and says how to see the rest.
async function otaHistOpen(){
  OH={st:"load"};view();scrollTo(0,0);
  let list=null,err="",http;
  try{
    const idx=await otaGet(otaSrc(OS_)+"/firmware/index.json"),ch=OS_&&OS_.ch;
    if(!idx||!Array.isArray(idx.releases))throw otaErr("bad");
    list=idx.releases.filter((e)=>e&&typeof e.version==="string"&&(!ch||e.channel===ch)).map((e)=>({v:e.version,d:typeof e.date==="string"?e.date:"",n:otaClean(e.notes)}));
  }catch(e){err=e.kind||"bad";if(e.kind==="http")http=e.status}
  const iv0=OS_&&OS_.v,mn={v:iv0,n:otaClean(iv0&&Object.prototype.hasOwnProperty.call(OTA_WN,iv0)?OTA_WN[iv0]:null)};
  if(!OH)return;                                   // closed meanwhile
  if(list){
    const iv=OS_&&OS_.v,r=otaFor(OS_),rv=r&&r.v;
    // Keep locally known Installed/Ready releases even if the index omits them or notes.
    for(const local of [mn,r&&{v:rv,n:otaClean(r.notes)}]){
      if(!local||!local.v)continue;
      const x=list.find((e)=>e.v===local.v);
      if(!x)list.push({...local,d:""});
      else if(!x.n.length)x.n=local.n;
    }
    list=list.filter((e)=>e.n.length||e.v===iv||e.v===rv).sort((a,b)=>vcmp(b.v,a.v));
    OH={st:"on",list};
  }else OH={st:"off",mine:mn,err,http};
  if(route==="set")view();
}
function otaDay(d){const t=Date.parse(d+"T12:00:00Z");return isNaN(t)?"":new Date(t).toLocaleDateString("en-US",{month:"short",day:"numeric",timeZone:"UTC"})}
function otaHistRow(e,iv,rv,short){
  const tag=e.v===iv?"Installed":e.v===rv?"Ready to install":otaDay(e.d);
  const nm=short?e.v.split("-")[0]:e.v;
  return `<section class="otahv${e.v===iv?" on":""}"><div class=lab><span class=m>${h(nm)}</span>${tag?`<span>${h(tag)}</span>`:""}</div>${e.n.length?otaNotes(e.n):`<p class=dim>No notes for this version.</p>`}</section>`;
}
function otaHist(){
  shipTop();
  const H=OH,iv=OS_&&OS_.v,r=otaFor(OS_),rv=r&&r.v;
  let o=`<div class=kick><div class=lab>Settings · Ship software</div><h1>Version history</h1><p class=dim>What changed in each version of your ship's software, newest first.</p></div>`;
  if(H.st==="load")o+=`<p class="dim otahl" role=status>Looking up versions…</p>`;
  else if(H.st==="on"){
    // the short number (0.3.0) unless two releases share it
    const b=H.list.map((e)=>e.v.split("-")[0]),short=new Set(b).size===b.length;
    o+=H.list.length?H.list.map((e)=>otaHistRow(e,iv,rv,short)).join(""):`<p class=dim>No versions with notes yet.</p>`;
  }else{
    const mn=H.mine;
    o+=mn.v?otaHistRow({v:mn.v,d:"",n:mn.n},iv,rv,false):"";
    const why=H.err==="timeout"?"The version history request timed out.":otaNet(H.err)?"Your phone couldn't reach GitHub on this network.":H.err==="http"?`You couldn't get version history from GitHub (HTTP ${H.http}). Try again later.`:"The version history data is invalid. Try again later.";
    o+=`<div class=otahc><p class=dim>${h(why)}${otaNet(H.err)?" Older versions are listed online. To see them, check again on mobile data or another Wi-Fi network.":""}</p><button class="btn sec" data-ota=hist><span>Check again</span><i>github</i></button></div>`;
  }
  $("v").innerHTML=o;
  dock(`<button class="btn sec" data-ota=back><span>Back</span><i>settings</i></button>`,"set");
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
function otaChecking(){return OTA_CHECK}
function otaFailure(b){
  if(b.err==="timeout")return"Your update check timed out. You can try again.";
  if(b.err==="network"||b.err==="offline")return"Your phone couldn't reach GitHub on this network.";
  if(b.err==="http")return`You couldn't get the update from GitHub (HTTP ${b.http}). Try again later.`;
  if(b.err==="full")return"Your phone couldn't store the update. Free some phone storage, then try again.";
  return"Your update data is invalid or missing a signature. Try again later.";
}
function otaAvail(st,b,r){
  if(r)return h(r.v);
  if(otaChecking())return "Checking…";
  if(b.at&&!b.ok)return "Couldn't check";
  return b.seen&&st&&vcmp(b.seen,st.v)<=0?"Up to date":b.seen?h(b.seen)+" (not signed for this ship)":"—";
}
// Settings' Ship software section: what runs, what's ready, Install and Check for updates.
function otaSect(){
  const st=OS_,b=OB||otaLoad(),r=otaFor(st),last=st&&st.last;
  let o=`<section id=set-sw><div class=lab><span>Ship software</span>${otaNag()?`<span class=otan><i>update ready</i></span>`:""}</div><dl class="facts otaf"><dt>Installed</dt><dd class=m>${st?h(st.v||"unknown"):"—"}</dd><dt>Channel</dt><dd>${st?h(st.ch||"—"):"—"}</dd><dt>Available</dt><dd class=m>${otaAvail(st,b,r)}</dd><dt>Checked</dt><dd>${otaChecking()?"Checking…":otaAgo(b.at)}</dd></dl>`;
  if(last&&last.result==="rolled back")o+=`<p class=upd><b>Went back</b> · ${h(last.v)} didn't start, so your ship returned to ${h(last.prev)}.</p>`;
  else if(last&&last.result==="installed"&&last.v===(st&&st.v))o+=`<p class=fine>${h(last.v)} installed over the air.</p>`;
  if(!st)o+=`<p class=dim>Your ship can't take updates over the air yet. It needs one install over USB first.</p>`;
  else if(r)o+=`<p>${h(r.v)} is ready on this phone for your ship. ${Math.round(r.bytes/1024)} KB, about a minute to send.</p>${otaClean(r.notes).length?`<div class=otawn><div class=otawh>What's new</div>${otaNotes(r.notes)}</div>`:""}<p class=dim>Your ship checks the signature and every file before it switches over, and goes back by itself if the new version doesn't start. Your crew, log and votes stay as they are.</p>`;
  else o+=`<p class=dim>You need internet to check. Your ship's Wi-Fi usually can't reach it. Keep this app open; your download waits on this phone until you rejoin your ship.</p>`;
  if(st){
    o+=`<div class=otas>${r?`<button class="btn pri" data-ota=install${OTA_CHECK?" disabled":""}><span>${otaNag()?"Install":"Try again:"} ${h(r.v)}</span><i>${Math.round(r.bytes/1024)} KB</i></button>`:""}<button class="btn sec" data-ota=check${OTA_CHECK?" disabled aria-busy=true":""} aria-describedby=otacheck><span>${OTA_CHECK?"Checking…":"Check for updates"}</span><i>github</i></button><div id=otacheck role=status>`;
    if(!OTA_CHECK&&b.err)o+=`<p class=err>${h(otaFailure(b))}</p>`;
    if(!OTA_CHECK&&otaNet(b.err))o+=`<ol class="otasteps dim"><li>Turn Wi-Fi off, or move away from your ship so you can use mobile data.</li><li>Stay in this app. Don't close it or switch to Safari; its storage is separate.</li><li>Tap Check for updates. Wait until you see “ready on this phone”.</li><li>Turn Wi-Fi back on, rejoin your ship's network, then tap Install.</li></ol>`;
    o+=`</div><button class="btn sec" data-ota=hist><span>Version history</span><i>what's new</i></button></div>`;
  }
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
  if(k==="check")return otaCheck(true);
  if(k==="reload")return location.reload();
  if(k==="clear"){OI=null;return view()}
  if(k==="hist")return otaHistOpen();
  if(k==="back"){OH=null;view();scrollTo(0,0);return document.querySelector("[data-ota=hist]")?.focus()}
});
// Internet back (left the hotspot, or the phone found another route): look again.
addEventListener("online",()=>otaCheck(false));
document.addEventListener("visibilitychange",()=>{if(!document.hidden)otaCheck(false)});

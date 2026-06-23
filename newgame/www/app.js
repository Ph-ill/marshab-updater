const S={state:null,tab:'hab',content:{},diag:null,lastMsg:'',fetchedAt:0,logSeeded:false,tutStep:0,tutDone:false,tutTarget:'',resOpen:false};
const $=q=>document.querySelector(q);
const TYPES=['actions','beats','archive','events','away','ui','ending','letters'];
const ICON={o2:'🫁',power:'⚡',water:'💧',food:'🥫',regolith:'🪨',population:'👥',atmosphere:'🌫️',temperature:'🌡️',biomass:'🌱',ice:'🧊',alloy:'🔩',polymer:'🧪',rare_metals:'💎',vent_co2:'🌬️',reroute_power:'⚡',collect_ice:'🧊',sift_regolith:'🪨',grow_rations:'🌱',decode_signal:'📡',survey_crater:'🛞',print_spares:'🛠️',stabilize_dome:'🏕️',run_atmo_processor:'🌫️',seed_bioreactor:'🧫',open_airlock:'🚪'};
const FALLBACK={ui_tab_hab:'Hab',ui_tab_surface:'Surface',ui_tab_colony:'Colony',ui_tab_trade:'Trade',ui_tab_archive:'Archive',ui_tab_ending:'End',ui_header_actions:'Operations',ui_header_archive:'Archive',ui_header_letters:'Letters',ui_header_ending:'Finale',ui_button_copy_code:'Copy Code',ui_button_redeem_code:'Redeem Code',ui_button_tend:'Tend',ui_resource_o2:'O₂',ui_resource_power:'Power',ui_resource_water:'Water',ui_resource_food:'Rations',ui_resource_regolith:'Regolith',ui_resource_population:'Crew',ui_resource_atmosphere:'Atmosphere',ui_resource_temperature:'Temp',ui_resource_biomass:'Biomass',ui_resource_alloy:'Alloy',ui_resource_polymer:'Polymer',ui_resource_rare_metals:'Rare Metals',ui_resource_ice:'Ice'};
const ACTION_FALLBACK={vent_co2:{label:'Vent CO₂',flavor:'Bleed stale air through the scrubbers.'},reroute_power:{label:'Reroute Power',flavor:'Balance batteries and sun-starved circuits.'},collect_ice:{label:'Collect Ice',flavor:'Send drones to scrape usable ice.'},sift_regolith:{label:'Sift Regolith',flavor:'Sort dust and rock into feedstock.'},grow_rations:{label:'Grow Rations',flavor:'Tend the trays until dinner looks possible.'},decode_signal:{label:'Decode Signal',flavor:'Pull another pattern from the buried transmission.'},survey_crater:{label:'Survey Crater',flavor:'Roll beyond the lights and map useful ground.'},print_spares:{label:'Print Spares',flavor:'Turn polymer and alloy into emergency parts.'},stabilize_dome:{label:'Stabilize Dome',flavor:'Seal seams and settle the pressure envelope.'},run_atmo_processor:{label:'Run Atmo Processor',flavor:'Push another breath into the Martian sky.'},seed_bioreactor:{label:'Seed Bioreactor',flavor:'Wake the microbes and feed the slow green engine.'},open_airlock:{label:'Open Airlock',flavor:'Step into the changed world.'}};
function log(m){if(!m)return;let li=document.createElement('li');li.textContent=m;$('#log').prepend(li)}
async function api(p,o={}){let r=await fetch(p,{method:o.body?'POST':(o.method||'GET'),headers:{'Content-Type':'application/json'},body:o.body&&JSON.stringify(o.body)});return r.json()}
function carried(){try{return JSON.parse(localStorage.getItem('marsHabPackages')||'[]')}catch(e){return []}}
function loadTut(){try{S.tutDone=localStorage.getItem('marsHabTutorialDone')==='1';S.tutStep=Math.max(0,Math.min(5,+(localStorage.getItem('marsHabTutorialStep')||'0')))}catch(e){}}
function tutDone(){return S.tutDone}
function tutStep(){return S.tutStep||0}
function setTutStep(n){S.tutStep=Math.max(0,Math.min(5,n));if(S.tutStep===5)S.tab='comms';else if(S.tutStep<5)S.tab='hab';try{localStorage.setItem('marsHabTutorialStep',String(S.tutStep))}catch(e){}}
function closeTut(done){if(done){S.tutDone=true;try{localStorage.setItem('marsHabTutorialDone','1')}catch(e){}}render()}
function openTut(){S.tutDone=false;setTutStep(0);try{localStorage.removeItem('marsHabTutorialDone')}catch(e){}render()}
function tutorial(){if(tutDone()||!S.state)return '';let s=S.state,u=s.upgrades||{},step=tutStep();let steps=[
 {t:'Wake the hab',b:'You are the colony automation. Keep the crew alive, then turn Mars into a place that can breathe.',a:'Start guide'},
 {t:'Read the resource strip',b:'The top panel is your life support dashboard. Icons show O₂, power, water, rations, crew, and later terraforming progress. Green numbers are per-sol rates.',a:'Next',target:'#res'},
 {t:'Tap operations',b:'Operations are active commands. Tap Vent CO₂, Reroute Power, Collect Ice, or Sift Regolith when they are ready. The amber fill shows cooldown.',a:'Next',target:'[data-guide=ops]'},
 {t:'Build the first loop',b:'Spend resources on modules. Your first practical goal is Solar Array → Ice Well → Greenhouse so power, water, food, and oxygen become renewable.',a:'Next',target:'[data-guide=mods]'},
 {t:'Check in, then leave it running',b:'MarsHab is idle. Progress continues while the hab has power. Check back later to collect gains and read new logs.',a:'Next',target:'#guide'},
 {t:'Trade later',b:'The Trade screen creates care-package codes and records passport visits. It helps, but the colony is still solo-completable.',a:'Finish',target:'[data-guide=trade]'}];
 let x=steps[step];S.tutTarget=x.target||'';let hint='';
 if(step===3){let built=['solar_array','ice_well','greenhouse'].filter(k=>(u[k]&&u[k].owned));hint=`<p class=muted>Built: ${built.length}/3 starter modules.</p>`}
 return `<div id=tutorial class=tut${step}><div class=tutShade></div><div class=tutCard><h2>🧭 ${x.t}</h2><p>${x.b}</p>${hint}<div class=tutBtns><button data-tut=skip>Skip</button><button data-tut=next>${x.a}</button></div></div></div>`}

function saveCarried(a){try{localStorage.setItem('marsHabPackages',JSON.stringify(a.slice(-12)))}catch(e){}}
function rememberCode(c){let a=carried();if(c&&!a.includes(c)){a.push(c);saveCarried(a)}}
function forgetCode(c){saveCarried(carried().filter(x=>x!==c))}
async function loadContent(t){if(!S.content[t]){try{S.content[t]=await api('/api/content/'+t)}catch(e){S.content[t]={}}}return S.content[t]}
function val(v,field){if(!v)return '';if(typeof v==='string')return v;if(field&&v[field])return v[field];if(v.text)return v.text;if(v.body&&v.title)return v.title+'\n\n'+v.body;if(v.body)return v.body;if(v.title)return v.title;if(v.label)return v.label;return JSON.stringify(v)}
function txt(t,id,field){let d=S.content[t]||{},key=id,result=null;if(t==='actions'){if(id.includes(':')){let p=id.split(':');key=p[0];result=p[1]}else if(!id.startsWith('act_'))key='act_'+id}let v=d[key];if(!v&&t==='ui')return FALLBACK[key]||FALLBACK[id]||id.replace(/^ui_(tab|resource|header|button)_/,'').replace(/_/g,' ');if(!v&&t==='actions'){let bare=key.replace(/^act_/,'');let f=ACTION_FALLBACK[bare]||{};return field==='flavor'?(f.flavor||'System ready.'):field==='label'?(f.label||bare.replace(/_/g,' ')):f.label||bare.replace(/_/g,' ')}if(!v)return '[STUB '+key+(result?':'+result:'')+']';return val(v,field||result)}
function icon(k){return ICON[k]||ICON[k.replace(/^act_/,'')]||'◈'}
function line(id){if(!id)return '';if(id.startsWith('act_'))return txt('actions',id);if(id.startsWith('beat_'))return txt('beats',id);if(id.startsWith('evt_'))return txt('events',id);if(id.startsWith('away_'))return txt('away',id);if(id.startsWith('end_'))return txt('ending',id);return id}
function fmt(n){if(n===undefined||n===null)return '0';if(Math.abs(n)>=100)return Math.round(n).toString();if(Math.abs(n)>=10)return (Math.round(n*10)/10).toString();return (Math.round(n*100)/100).toString()}
function pct(n){return fmt((n||0)*100)+'%'}
function nice(k){return txt('ui','ui_resource_'+k)||k.replace(/_/g,' ')}
function cost(c){return Object.keys(c||{}).map(k=>icon(k)+' '+nice(k)+' '+fmt(c[k])).join(' · ')||'free'}
function rate(v,k){if(!v)return '';let per=v*86400;if(k==='atmosphere'||k==='temperature'||k==='biomass')return (per>=0?'+':'')+fmt(per*100)+'/sol';return (per>=0?'+':'')+fmt(per)+'/sol'}
function res(){let s=S.state,r=s.resources||{},rates=s.rates||{},caps=s.caps||{};
 $('#res').className=S.resOpen?'open':'';
 let primary=['o2','power','water','food','regolith','population'];
 let secondary=['atmosphere','temperature','biomass','ice','alloy','polymer','rare_metals'];
 let relevant=k=>r[k]!==undefined&&((r[k]||0)>0||(rates[k]||0)!==0||['atmosphere','temperature','biomass'].includes(k)&&((s.act||1)>=3));
 let shown=primary.filter(k=>r[k]!==undefined), hidden=secondary.filter(relevant);
 let chip=k=>`<div class=r data-res="${k}"><b>${icon(k)} <span>${nice(k)}</span></b><strong>${k==='atmosphere'||k==='temperature'||k==='biomass'?pct(r[k]):fmt(r[k])}${S.resOpen&&caps[k]&&caps[k]<999999?' / '+fmt(caps[k]):''}</strong><em>${rate(rates[k],k)}</em></div>`;
 $('#res').innerHTML=`<div class=resTop>${shown.map(chip).join('')}<button id=resMore class=resMore>${S.resOpen?'Less ▲':'More ▾'} ${hidden.length?`(${hidden.length})`:''}</button></div>${S.resOpen&&hidden.length?`<div class=resDetail>${hidden.map(chip).join('')}</div>`:''}`;
}
function tabs(){let t=(S.state.tabs||['hab']).slice().filter(x=>x!=='diag');if(!t.includes('hab'))t.unshift('hab');return t.slice(0,4)}
function tabLabel(t){if(t==='comms')return '🤝 '+txt('ui','ui_tab_trade');if(t==='hab')return '🏠 Hab';if(t==='surface')return '🪐 Surface';if(t==='archive')return '📚 Archive';if(t==='colony')return '👥 Colony';if(t==='ending')return '🚪 End';return txt('ui','ui_tab_'+t)}
function serverNow(){return (S.state.now_ms||0)+(Date.now()-(S.fetchedAt||Date.now()))}
function actionButton(a){let cd=(S.state.cooldowns||{})[a]||0,rem=Math.max(0,cd-serverNow());let w=rem?Math.max(0,Math.min(100,rem/((a==='open_airlock'?300:15)*1000)*100)):0;return `<button data-act="${a}" ${rem>0?'disabled':''}><span class=fill style="width:${w}%"></span><b>${icon(a)} ${txt('actions',a,'label')}</b><small>${txt('actions',a,'flavor')}</small>${rem>0?`<em>${Math.ceil(rem/1000)}s</em>`:''}</button>`}
function moduleRates(r){return Object.keys(r||{}).map(k=>icon(k)+' '+nice(k)+' '+rate(r[k],k)).join(' · ')||'none'}
function moduleButton(id,m){let owned=m.owned||0,can=m.buildable!==false;let req=m.requires_env?`<small>requires: ${cost(m.requires_env)}</small>`:'';return `<button data-build="${id}" ${can?'':'disabled'}><b>🏗️ ${m.label} ${owned?`×${owned}`:''}</b><small>${m.desc||''}</small><small>cost: ${cost(m.cost)}</small>${req}<small>rates: ${moduleRates(m.rates)}</small></button>`}
function storyList(type,ids){if(!ids||!ids.length)return '<p class=muted>Nothing recovered yet.</p>';return ids.map(id=>`<article class=entry>${txt(type,id).replace(/\n/g,'<br>')}</article>`).join('')}
function bar(label,val,max,ico='') {let p=max?Math.max(0,Math.min(100,(val/max)*100)):0;return `<div class=bar><span>${ico} ${label}</span><b>${fmt(val)} / ${fmt(max||1)}</b><i style="width:${p}%"></i></div>`}
function envPanel(s){let e=s.environment||{},r=s.resources||{};return `<div class=grid>${bar('atmosphere',r.atmosphere||0,1,'🌫️')}${bar('temperature',r.temperature||0,1,'🌡️')}${bar('biomass',r.biomass||0,1,'🌱')}${bar('breathability',e.breathability_confidence||0,100,'🫁')}</div><p class=muted>pressure ${e.pressure_mb||6.1} mb; Armstrong exposure floor ${e.armstrong_limit_mb||62} mb. Airlock ready: ${e.open_air_ready?'yes':'no'}.</p>`}
function moduleSection(title,filter,mark=''){let u=S.state.upgrades||{},keys=Object.keys(u).filter(k=>filter(k,u[k]));return keys.length?`<div class=card ${mark?`data-guide=${mark}`:''}><h2>${title}</h2>${keys.map(k=>moduleButton(k,u[k])).join('')}</div>`:''}
function recentEvents(){return `<div class=card><h2>📜 Recent log</h2>${storyList('events',(S.state.events||[]).filter(x=>x.startsWith('evt_')).slice(-6).reverse())}</div>`}
function render(){if(!S.state)return;res();let s=S.state;if(!tabs().includes(S.tab))S.tab='hab';$('#tabs').innerHTML=tabs().map(t=>`<button data-tab=${t} class=${S.tab===t?'on':''}>${tabLabel(t)}</button>`).join('');let env=s.environment||{};let html=`<button id=guide class=guideBtn>🧭 Guide</button><div class=card><h1>🚀 Act ${s.act} // ${(s.device&&s.device.hab_name)||'Mars Hab'}</h1><p>${s.goal||''}</p><p class=muted>firmware ${s.version||'?'} · signature export: ${(s.device&&s.device.signature_resource)||'unknown'} · legacy ${s.legacy||0}</p><p class=muted>🌫️ ${env.pressure_mb||6.1} mb · 🫁 confidence ${env.breathability_confidence||0}%</p>${s.complete?'<p class=msg>ending complete. legacy multiplier active.</p>':''}${S.lastMsg?`<p class=msg>${S.lastMsg}</p>`:''}</div>`;
 if(S.tab==='hab')html+=`<div class=card data-guide=ops><h2>🕹️ ${txt('ui','ui_header_actions')}</h2>${(s.actions||[]).filter(a=>!['survey_crater','run_atmo_processor','seed_bioreactor','stabilize_dome'].includes(a)).map(actionButton).join('')}</div>`+moduleSection('🏠 Hab modules',(k,m)=>m.act<=2,'mods')+moduleSection('🪐 Terraforming modules',(k,m)=>m.act>=3,'mods');
 if(S.tab==='surface')html+=`<div class=card><h2>🪐 Surface Operations</h2>${envPanel(s)}${(s.actions||[]).filter(a=>['survey_crater','run_atmo_processor','seed_bioreactor','stabilize_dome'].includes(a)).map(actionButton).join('')||'<p class=muted>Build industry to unlock expeditions and terraforming controls.</p>'}</div>${recentEvents()}`;
 if(S.tab==='colony')html+=`<div class=card><h2>👥 Colony</h2>${bar('population',(s.resources||{}).population||0,(s.caps||{}).population||12,'👥')}${bar('food stores',(s.resources||{}).food||0,(s.caps||{}).food||80,'🥫')}${bar('oxygen reserve',(s.resources||{}).o2||0,(s.caps||{}).o2||100,'🫁')}<p class=muted>Letters unlock as the colony stabilizes and the act advances.</p>${storyList('letters',s.letters)}</div>`;
 if(S.tab==='comms'){let p=s.passport||{visits:[]},packs=carried();html+=`<div class=card data-guide=trade><h2>🤝 ${txt('ui','ui_tab_trade')}</h2><p class=muted>Passport visits: ${(p.visits||[]).length} · production bonus ${Math.round((s.passport_bonus||0)*100)}%</p><button id=pkg>📦 ${txt('ui','ui_button_copy_code')}</button><p id=code class=code></p><textarea id=redeem placeholder="paste code"></textarea><button id=redeemBtn>🎟️ ${txt('ui','ui_button_redeem_code')}</button><button id=tend>🧤 ${txt('ui','ui_button_tend')}</button></div><div class=card><h2>🎒 Carried packages</h2>${packs.length?packs.map(c=>`<button data-redeem-stored="${c}"><b>🎟️ Redeem carried package</b><small>${c}</small></button>`).join(''):'<p class=muted>No carried packages in this browser.</p>'}</div>`}
 if(S.tab==='archive')html+=`<div class=card><h2>📚 ${txt('ui','ui_header_archive')}</h2><p class=muted>${(s.archive||[]).length} archive entries · ${(s.letters||[]).length} letters recovered</p>${storyList('archive',s.archive)}</div><div class=card><h2>✉️ ${txt('ui','ui_header_letters')}</h2>${storyList('letters',s.letters)}</div>`;
 if(S.tab==='ending')html+=`<div class=card><h2>🚪 ${txt('ui','ui_header_ending')}</h2>${envPanel(s)}${storyList('ending',s.ending)}${s.complete?'<button id=newGamePlus>🔁 Begin New Game+ // keep legacy</button>':'<p class=muted>Reach airlock-ready conditions to unlock the final sequence.</p>'}</div>`;
 $('#screen').innerHTML=html+tutorial();applyGuide()}
function applyGuide(){
 document.querySelectorAll('.guideFocus').forEach(e=>e.classList.remove('guideFocus'));
 let tut=document.querySelector('#tutorial');if(tut){tut.classList.remove('placeTop','placeBottom')}
 if(tutDone()||!S.tutTarget)return;
 let el=document.querySelector(S.tutTarget);if(!el)return;el.classList.add('guideFocus');
 requestAnimationFrame(()=>placeAndScrollGuide(el));
}
function placeAndScrollGuide(el){
 let tut=document.querySelector('#tutorial'),card=document.querySelector('.tutCard');if(!tut||!card||!el)return;
 let vh=window.innerHeight||document.documentElement.clientHeight||640,margin=14;
 let nav=document.querySelector('nav'),nr=nav?nav.getBoundingClientRect():{top:vh};
 let usableTop=margin,usableBottom=Math.min(vh-margin,nr.top-margin);
 let er=el.getBoundingClientRect(),targetMid=(er.top+er.bottom)/2;
 let spaceAbove=Math.max(0,er.top-usableTop-margin),spaceBelow=Math.max(0,usableBottom-er.bottom-margin);
 tut.classList.remove('placeTop','placeBottom');
 if(spaceAbove>=spaceBelow)tut.classList.add('placeTop');else tut.classList.add('placeBottom');
 requestAnimationFrame(()=>{
  let cr=card.getBoundingClientRect();
  let topGap=usableTop,bottomGap=usableBottom;
  if(tut.classList.contains('placeTop'))topGap=Math.min(bottomGap,cr.bottom+margin);else bottomGap=Math.max(topGap,cr.top-margin);
  if(bottomGap-topGap<80){topGap=usableTop;bottomGap=usableBottom}
  let er2=el.getBoundingClientRect(),space=bottomGap-topGap,actual=(er2.top+er2.bottom)/2,desired=(topGap+bottomGap)/2;
  if(er2.height>space){
   if(tut.classList.contains('placeTop')){actual=er2.top;desired=topGap}else{actual=er2.bottom;desired=bottomGap}
  }
  let maxY=Math.max(0,document.documentElement.scrollHeight-vh);
  let next=Math.max(0,Math.min(maxY,window.scrollY+actual-desired));
  window.scrollTo({top:next,behavior:'smooth'});
 });
}
async function sync(){let min=new Promise(r=>setTimeout(r,1200));let p=api('/api/sync',{body:{now:Date.now()}});let [st]=await Promise.all([p,min]);S.state=st;S.fetchedAt=Date.now();await Promise.all(TYPES.map(loadContent));$('#load').classList.add('hide');if(!S.logSeeded){(st.events||[]).slice(-8).reverse().forEach(id=>log(line(id)));S.logSeeded=true}if(st.away_report&&st.away_report.elapsed_ms){let parts=(st.away_report.away||[]).map(id=>txt('away',id));(st.away_report.beats||[]).forEach(id=>log(txt('beats',id)));log(parts.length?parts.join(' / '):('while away: '+Object.entries(st.away_report.gains||{}).map(([k,v])=>nice(k)+' '+fmt(v)).join(', ')))}render()}
async function refreshDiag(){S.diag=await api('/api/diagnostics')}
document.body.onclick=async e=>{let rc=e.target.closest('.r');if(rc&&rc.closest('#res')&&!S.resOpen){rc.classList.add('showName');clearTimeout(rc._t);rc._t=setTimeout(()=>rc.classList.remove('showName'),1300);return}let b=e.target.closest('button');if(!b)return;if(b.id==='resMore'){S.resOpen=!S.resOpen;render();return}if(b.dataset.tut){if(b.dataset.tut==='skip')closeTut(true);else{let n=tutStep()+1;if(n>5)closeTut(true);else{setTutStep(n);render()}}return}if(b.id==='guide'){openTut();return}if(b.dataset.tab){S.tab=b.dataset.tab;render();return}if(b.dataset.act){let st=await api('/api/action',{body:{action_id:b.dataset.act}});S.state=st;S.fetchedAt=Date.now();S.lastMsg=st.result&&st.result.ok?'action complete':((st.result&&st.result.error)||'action failed');if(st.result&&st.result.event)log(line(st.result.event));if(st.result&&st.result.beats)(st.result.beats||[]).forEach(id=>log(txt('beats',id)));render();return}if(b.dataset.build){let st=await api('/api/action',{body:{action_id:'build',module_id:b.dataset.build}});S.state=st;S.fetchedAt=Date.now();S.lastMsg=st.result&&st.result.ok?'module built':((st.result&&st.result.error)||'build failed');if(st.result&&st.result.beats)(st.result.beats||[]).forEach(id=>log(txt('beats',id)));render();return}if(b.dataset.redeemStored){let code=b.dataset.redeemStored;S.state=await api('/api/trade/redeem',{body:{code}});S.fetchedAt=Date.now();if(S.state.result&&S.state.result.ok)forgetCode(code);S.lastMsg=(S.state.result&&S.state.result.ok)?'carried package redeemed':((S.state.result&&S.state.result.error)||'redeem failed');render();return}if(b.id==='pkg'){let r=await api('/api/trade/package');$('#code').textContent=r.code;rememberCode(r.code);render();return}if(b.id==='redeemBtn'){let code=$('#redeem').value;S.state=await api('/api/trade/redeem',{body:{code}});S.fetchedAt=Date.now();if(S.state.result&&S.state.result.ok)forgetCode(code);S.lastMsg=(S.state.result&&S.state.result.ok)?'package redeemed':((S.state.result&&S.state.result.error)||'redeem failed');render();return}if(b.id==='tend'){S.state=await api('/api/tend',{body:{visitor:'guest'}});S.fetchedAt=Date.now();S.lastMsg='host tended';render();return}if(b.id==='newGamePlus'){S.state=await api('/api/action',{body:{action_id:'new_game_plus'}});S.fetchedAt=Date.now();S.lastMsg=(S.state.result&&S.state.result.ok)?'new game+ started':((S.state.result&&S.state.result.error)||'reset failed');S.tab='hab';render();return}};
setInterval(async()=>{if(!S.state)return;S.state=await api('/api/state');S.fetchedAt=Date.now();render()},2000);
loadTut();
sync();

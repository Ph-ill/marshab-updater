const S={state:null,tab:'hab',content:{},lastSync:0};
const $=q=>document.querySelector(q);
const log=m=>{let li=document.createElement('li');li.textContent=m;$('#log').prepend(li)};
async function api(p,o={}){let r=await fetch(p,{method:o.body?'POST':(o.method||'GET'),headers:{'Content-Type':'application/json'},body:o.body&&JSON.stringify(o.body)});return r.json()}
async function loadContent(t){if(!S.content[t])S.content[t]=await api('/api/content/'+t);return S.content[t]}
function val(v,field){
  if(!v)return '';
  if(typeof v==='string')return v;
  if(field&&v[field])return v[field];
  if(v.text)return v.text;
  if(v.body&&v.title)return v.title+'\n\n'+v.body;
  if(v.body)return v.body;
  if(v.title)return v.title;
  if(v.label)return v.label;
  return JSON.stringify(v);
}
function txt(t,id,field){
  let d=S.content[t]||{}, key=id, result=null;
  if(t==='actions'){
    if(id.includes(':')){let p=id.split(':');key=p[0];result=p[1]}
    else if(!id.startsWith('act_'))key='act_'+id;
  }
  let v=d[key];
  if(!v)return '[STUB '+key+(result?':'+result:'')+']';
  return val(v,field||result);
}
function res(){let s=S.state,r=s.resources||{},rates=s.rates||{};$('#res').innerHTML=Object.keys(r).slice(0,9).map(k=>`<div class=r>${k}: ${fmt(r[k])}<div class=rate>${rates[k]?fmt(rates[k]*86400)+'/sol':''}</div></div>`).join('')}
function fmt(n){return (Math.round(n*100)/100).toString()}
function actionButton(a){let cd=(S.state.cooldowns||{})[a]||0,rem=Math.max(0,cd-performance.timeOrigin-Date.now()+performance.now());return `<button data-act="${a}" ${rem>0?'disabled':''}><span class=fill style="width:${rem>0?100:0}%"></span>${txt('actions',a,'label')}</button>`}
function render(){
  res();let s=S.state,tabs=s.tabs||['hab'];
  const tabLabel=t=>txt('ui',t==='comms'?'ui_tab_trade':'ui_tab_'+t);
  $('#tabs').innerHTML=tabs.map(t=>`<button data-tab=${t}>${tabLabel(t)}</button>`).join('');
  let html='<div class=card><h1>Act '+s.act+' // '+(s.device.hab_name||'Mars Hab')+'</h1><p class=muted>signature export: '+s.device.signature_resource+'</p></div>';
  if(S.tab==='hab')html+='<div class=card><h2>'+txt('ui','ui_header_actions')+'</h2>'+s.actions.map(actionButton).join('')+'</div><div class=card><h2>'+txt('ui','ui_header_modules')+'</h2>'+Object.keys(s.upgrades||{}).map(k=>`<button data-build="${k}">${s.upgrades[k].label}</button>`).join('')+'</div>';
  if(S.tab==='surface')html+='<div class=card><h2>Surface</h2><p>'+txt('events','evt_weather_dust_storm_minor')+'</p></div>';
  if(S.tab==='comms')html+='<div class=card><h2>'+txt('ui','ui_tab_trade')+'</h2><button id=pkg>'+txt('ui','ui_button_copy_code')+'</button><p id=code class=code></p><textarea id=redeem placeholder="paste code"></textarea><button id=redeemBtn>'+txt('ui','ui_button_redeem_code')+'</button><button id=tend>'+txt('ui','ui_button_tend')+'</button></div>';
  if(S.tab==='archive')html+='<div class=card><h2>'+txt('ui','ui_header_archive')+'</h2>'+s.archive.map(id=>`<p>${txt('archive',id).replace(/\n/g,'<br>')}</p>`).join('')+'</div>';
  $('#screen').innerHTML=html;
}
async function sync(){
  let min=new Promise(r=>setTimeout(r,1200));let p=api('/api/sync',{body:{now:Date.now()}});let [st]=await Promise.all([p,min]);S.state=st;
  await Promise.all(['actions','beats','archive','events','away','ui','ending','letters'].map(loadContent));
  $('#load').classList.add('hide');
  if(st.away_report&&st.away_report.elapsed_ms){
    let parts=(st.away_report.away||[]).map(id=>txt('away',id));
    log(parts.length?parts.join(' / '):('while away: '+Object.entries(st.away_report.gains).map(([k,v])=>k+' '+fmt(v)).join(', ')));
  }
  render();
}
document.body.onclick=async e=>{
  let b=e.target.closest('button');if(!b)return;
  if(b.dataset.tab){S.tab=b.dataset.tab;render()}
  if(b.dataset.act){S.state=await api('/api/action',{body:{action_id:b.dataset.act}});if(S.state.result&&S.state.result.event)log(txt('actions',S.state.result.event));render()}
  if(b.dataset.build){S.state=await api('/api/action',{body:{action_id:'build',module_id:b.dataset.build}});if(S.state.result&&S.state.result.beats)(S.state.result.beats||[]).forEach(id=>log(txt('beats',id)));render()}
  if(b.id==='pkg'){let r=await api('/api/trade/package');$('#code').textContent=r.code}
  if(b.id==='redeemBtn'){S.state=await api('/api/trade/redeem',{body:{code:$('#redeem').value}});render()}
  if(b.id==='tend'){S.state=await api('/api/tend',{body:{visitor:'guest'}});render()}
};
setInterval(async()=>{if(!S.state)return;S.state=await api('/api/state');render()},2000);
sync();

import time, gc
MAX_RATE_SEC=60*60*24*30
RES_ORDER=('o2','power','water','food','regolith','population','ice','rare_metals','polymer','alloy','atmosphere','temperature','biomass')
ACTIONS={
 'vent_co2':{'label':'vent co2','cooldown_ms':15000,'effect':{'o2':8},'event':'evt_vent_co2'},
 'reroute_power':{'label':'reroute power','cooldown_ms':20000,'effect':{'power':12},'event':'evt_reroute_power'},
 'collect_ice':{'label':'collect ice','cooldown_ms':30000,'effect':{'water':8,'ice':2},'cost':{'power':2},'event':'evt_collect_ice'},
 'sift_regolith':{'label':'sift regolith','cooldown_ms':25000,'effect':{'regolith':18},'event':'evt_sift_regolith'},
 'grow_rations':{'label':'grow rations','cooldown_ms':45000,'effect':{'food':10},'cost':{'water':3,'power':2},'event':'evt_grow_rations'},
 'decode_signal':{'label':'decode signal','cooldown_ms':90000,'effect':{},'cost':{'power':10},'event':'evt_decode_signal'},
 'run_atmo_processor':{'label':'run atmo processor','cooldown_ms':120000,'effect':{'atmosphere':0.002},'cost':{'power':20,'regolith':30},'event':'evt_atmo_processor'}
}
MODULES={
 'solar_array':{'label':'solar array','cost':{'regolith':80},'rates':{'power':0.025},'caps':{'power':50},'unlock':['grow_rations']},
 'ice_well':{'label':'ice well','cost':{'regolith':120,'power':40},'rates':{'water':0.018},'caps':{'water':60}},
 'greenhouse':{'label':'greenhouse','cost':{'water':60,'power':70,'regolith':140},'rates':{'food':0.014,'o2':0.01},'caps':{'food':80,'population':4}},
 'fab_shop':{'label':'fabricator shop','cost':{'regolith':240,'power':160},'rates':{'polymer':0.004,'alloy':0.003},'unlock':['decode_signal']},
 'atmo_processor':{'label':'atmosphere processor','cost':{'alloy':40,'polymer':35,'power':250},'rates':{'atmosphere':0.00000025},'unlock':['run_atmo_processor']}
}
MILESTONES=[
 {'act':2,'cond':lambda s:s['resources'].get('population',0)>=8 or s['modules'].get('greenhouse',0)>0,'beat':'beat_act2_open','tab':'colony'},
 {'act':3,'cond':lambda s:s['modules'].get('fab_shop',0)>0,'beat':'beat_act3_open','tab':'trade'},
 {'act':4,'cond':lambda s:s['modules'].get('atmo_processor',0)>0,'beat':'beat_act4_open','tab':'archive'},
 {'act':5,'cond':lambda s:s['resources'].get('atmosphere',0)>=1,'beat':'beat_act5_open','tab':'archive'}]
def now_ms():
    return time.ticks_ms() if hasattr(time, 'ticks_ms') else int(time.time() * 1000)
def ticks_diff(a,b):
    return time.ticks_diff(a,b) if hasattr(time, 'ticks_diff') else a-b
def rates(s,device=None):
    r={'o2':-0.001*s['resources'].get('population',0),'power':0.006,'water':-0.0005*s['resources'].get('population',0),'food':-0.0004*s['resources'].get('population',0),'regolith':0.002}
    for mid,n in s.get('modules',{}).items():
        m=MODULES.get(mid,{})
        for k,v in m.get('rates',{}).items(): r[k]=r.get(k,0)+v*n
    for _k,t in list(s.get('tends',{}).items()):
        if t.get('until_ms',0)>now_ms():
            for k in list(r):
                if r[k]>0: r[k]*=1.1
    return r
def snapshot(s,device=None):
    return {'version':'0.2.0','device':device or {},'act':s.get('act',1),'resources':s.get('resources',{}),'caps':s.get('caps',{}),'rates':rates(s,device),'modules':s.get('modules',{}),'actions':available_actions(s),'upgrades':available_modules(s),'cooldowns':s.get('cooldowns',{}),'tabs':s.get('unlocked_tabs',[]),'archive':s.get('archive',[]),'events':s.get('events',[])[-20:]}
def clamp_res(s):
    caps=s.setdefault('caps',{})
    for k,v in list(s.setdefault('resources',{}).items()):
        cap=caps.get(k, 999999 if k in ('atmosphere','temperature','biomass') else 1000)
        if v<0: s['resources'][k]=0
        elif v>cap: s['resources'][k]=cap
def advance(s, elapsed_ms, device=None):
    sec=max(0,min(MAX_RATE_SEC,elapsed_ms/1000)); before=dict(s.get('resources',{})); rr=rates(s,device)
    for k,v in rr.items(): s['resources'][k]=s['resources'].get(k,0)+v*sec
    # simple population growth if stable
    if s['resources'].get('food',0)>30 and s['resources'].get('o2',0)>30 and sec>3600:
        s['resources']['population']=s['resources'].get('population',0)+min(2,sec/86400*0.08)
    clamp_res(s); beats=[]; check_milestones(s,beats)
    gains={k:round(s['resources'].get(k,0)-before.get(k,0),2) for k in s['resources'] if abs(s['resources'].get(k,0)-before.get(k,0))>=0.01}
    gc.collect(); return {'elapsed_ms':int(sec*1000),'gains':gains,'beats':beats,'away':['away_power_hum','away_dust_on_panels'] if sec>3600 else []}
def check_cost(s,cost): return all(s['resources'].get(k,0)>=v for k,v in cost.items())
def pay(s,cost):
    for k,v in cost.items(): s['resources'][k]=s['resources'].get(k,0)-v
def apply_effect(s,effect):
    for k,v in effect.items(): s['resources'][k]=s['resources'].get(k,0)+v
    clamp_res(s)
def available_actions(s): return [a for a in s.get('unlocked_actions',[]) if a in ACTIONS]
def available_modules(s): return {k:v for k,v in MODULES.items() if k not in s.get('modules',{}) or s['modules'].get(k,0)<99}
def action(s,aid,now=None):
    now=now or now_ms(); a=ACTIONS.get(aid)
    if not a: return {'ok':False,'error':'unknown action'}
    if aid not in available_actions(s): return {'ok':False,'error':'locked'}
    if s.setdefault('cooldowns',{}).get(aid,0)>now: return {'ok':False,'error':'cooldown'}
    if not check_cost(s,a.get('cost',{})): return {'ok':False,'error':'insufficient'}
    pay(s,a.get('cost',{})); apply_effect(s,a.get('effect',{})); s['cooldowns'][aid]=now+a.get('cooldown_ms',10000)
    ev=a.get('event');
    if ev: s.setdefault('events',[]).append(ev)
    return {'ok':True,'event':ev}
def build(s,mid):
    m=MODULES.get(mid)
    if not m: return {'ok':False,'error':'unknown module'}
    if not check_cost(s,m.get('cost',{})): return {'ok':False,'error':'insufficient'}
    pay(s,m.get('cost',{})); s.setdefault('modules',{})[mid]=s['modules'].get(mid,0)+1
    for k,v in m.get('caps',{}).items(): s.setdefault('caps',{})[k]=s['caps'].get(k,100)+v
    for a in m.get('unlock',[]):
        if a not in s.setdefault('unlocked_actions',[]): s['unlocked_actions'].append(a)
    beats=[]; check_milestones(s,beats)
    return {'ok':True,'beats':beats}
def check_milestones(s,beats):
    for m in MILESTONES:
        if s.get('act',1)<m['act'] and m['cond'](s):
            s['act']=m['act']; beats.append(m['beat']); s.setdefault('events',[]).append(m['beat'])
            if m.get('tab') and m['tab'] not in s.setdefault('unlocked_tabs',[]): s['unlocked_tabs'].append(m['tab'])

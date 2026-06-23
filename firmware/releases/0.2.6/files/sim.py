import time, gc
import content_schema as schema
MAX_RATE_SEC=60*60*24*30
RES_ORDER=('o2','power','water','food','regolith','population','ice','rare_metals','polymer','alloy','atmosphere','temperature','biomass')
ACTIONS={
 'vent_co2':{'label':'vent co2','cooldown_ms':15000,'effect':{'o2':8}},
 'reroute_power':{'label':'reroute power','cooldown_ms':20000,'effect':{'power':12}},
 'collect_ice':{'label':'collect ice','cooldown_ms':30000,'effect':{'water':8,'ice':2},'cost':{'power':2}},
 'sift_regolith':{'label':'sift regolith','cooldown_ms':25000,'effect':{'regolith':18}},
 'grow_rations':{'label':'grow rations','cooldown_ms':45000,'effect':{'food':10},'cost':{'water':3,'power':2}},
 'decode_signal':{'label':'decode signal','cooldown_ms':90000,'effect':{},'cost':{'power':10},'counter':'decode_count'},
 'run_atmo_processor':{'label':'run atmo processor','cooldown_ms':120000,'effect':{'atmosphere':0.002},'cost':{'power':20,'regolith':30}},
 'survey_crater':{'label':'survey crater','cooldown_ms':90000,'effect':{'rare_metals':2},'cost':{'power':8},'counter':'survey_count'},
 'print_spares':{'label':'print spares','cooldown_ms':75000,'effect':{'alloy':1,'polymer':1},'cost':{'power':12,'regolith':20}},
 'seed_bioreactor':{'label':'seed bioreactor','cooldown_ms':150000,'effect':{'biomass':0.005},'cost':{'water':8,'food':5,'power':15}},
 'stabilize_dome':{'label':'stabilize dome','cooldown_ms':120000,'effect':{'temperature':0.01},'cost':{'power':18,'alloy':1}},
 'open_airlock':{'label':'open airlock','cooldown_ms':300000,'effect':{},'cost':{'atmosphere':1}}
}
MODULES={
 'solar_array':{'label':'solar array','cost':{'regolith':80},'rates':{'power':0.025},'caps':{'power':50},'unlock':['grow_rations'],'beat':'beat_first_solar_array'},
 'ice_well':{'label':'ice well','cost':{'regolith':120,'power':40},'rates':{'water':0.018},'caps':{'water':60},'beat':'beat_first_ice_well'},
 'greenhouse':{'label':'greenhouse','cost':{'water':60,'power':70,'regolith':140},'rates':{'food':0.014,'o2':0.01},'caps':{'food':80,'population':4},'beat':'beat_first_greenhouse'},
 'fab_shop':{'label':'fabricator shop','cost':{'regolith':240,'power':160},'rates':{'polymer':0.004,'alloy':0.003},'unlock':['decode_signal','survey_crater','print_spares','stabilize_dome'],'beat':'beat_first_fab_shop'},
 'atmo_processor':{'label':'atmosphere processor','cost':{'alloy':40,'polymer':35,'power':250},'rates':{'atmosphere':0.00000025},'unlock':['run_atmo_processor','seed_bioreactor'],'beat':'beat_first_atmo_processor'}
}
MILESTONES=[
 {'act':2,'cond':lambda s:s['resources'].get('population',0)>=8 or s['modules'].get('greenhouse',0)>0,'beat':'beat_act2_open','tab':'colony'},
 {'act':3,'cond':lambda s:s['modules'].get('fab_shop',0)>0,'beat':'beat_act3_open','tab':'trade'},
 {'act':4,'cond':lambda s:s['modules'].get('atmo_processor',0)>0,'beat':'beat_act4_open','tab':'archive'},
 {'act':5,'cond':lambda s:s['resources'].get('atmosphere',0)>=1,'beat':'beat_act5_open','tab':'archive'}]
INTERNAL_BEATS=[
 ('beat_population_8',lambda s:s['resources'].get('population',0)>=8),('beat_population_12',lambda s:s['resources'].get('population',0)>=12),('beat_decode_3',lambda s:s['counters'].get('decode_count',0)>=3),('beat_atmosphere_025',lambda s:s['resources'].get('atmosphere',0)>=.25),('beat_atmosphere_050',lambda s:s['resources'].get('atmosphere',0)>=.5),('beat_biomass_trace',lambda s:s['resources'].get('biomass',0)>0),('beat_final_threshold',lambda s:s['act']>=5)]

def now_ms(): return time.ticks_ms() if hasattr(time,'ticks_ms') else int(time.time()*1000)
def ticks_diff(a,b): return time.ticks_diff(a,b) if hasattr(time,'ticks_diff') else a-b

def rng(s,mod):
    x=(int(s.get('rng',12345))*1103515245+12345)&0x7fffffff; s['rng']=x
    return x%mod if mod else x

def choose_weighted(s,weighted,recent_key='event_recent',recent_limit=8):
    recent=s.setdefault(recent_key,[])[-recent_limit:]
    opts=[x for x in weighted if x[0] not in recent] or weighted
    total=sum(x[1] for x in opts); pick=rng(s,total); acc=0
    for cid,w in opts:
        acc+=w
        if pick<acc:
            recent.append(cid); s[recent_key]=recent[-recent_limit:]
            return cid
    return opts[-1][0]

def draw_event(s,pool=None):
    act=s.get('act',1); pools=[pool] if pool else list(schema.POOLS)
    for _ in range(len(pools)):
        p=pools[rng(s,len(pools))]
        weighted=schema.event_pool_ids(p,act)
        if weighted: return choose_weighted(s,weighted,'event_recent',10)
    return None

def draw_events(s,count):
    out=[]
    for _ in range(max(0,min(8,int(count)))):
        cid=draw_event(s)
        if cid and cid not in out: out.append(cid)
    s.setdefault('events',[]).extend(out)
    s['events']=s['events'][-80:]
    return out

def action_result_id(s,aid):
    # Result variants are fields inside act_<aid>; return field key for the UI/log to resolve.
    return 'result_%d'%(rng(s,4)+1)

def away_fragments(s,gains,event_ids,sec):
    if sec<1800: return []
    act=s.get('act',1); candidates=[]
    for e in schema.away_entries():
        a=str(e.get('act','1-5')); lo=int(a.split('-')[0]); hi=int(a.split('-')[-1])
        if lo<=act<=hi: candidates.append((e['id'],4 if e.get('pool')=='systems' else 3))
    count=2+(1 if sec>6*3600 else 0)+(1 if event_ids else 0)+(1 if len(gains)>3 else 0)
    out=[]
    for _ in range(min(count,5)):
        cid=choose_weighted(s,candidates,'away_recent',10)
        if cid not in out: out.append(cid)
    return out

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
    return {'version':'0.2.4','device':device or {},'act':s.get('act',1),'resources':s.get('resources',{}),'caps':s.get('caps',{}),'rates':rates(s,device),'modules':s.get('modules',{}),'actions':available_actions(s),'upgrades':available_modules(s),'cooldowns':s.get('cooldowns',{}),'tabs':s.get('unlocked_tabs',[]),'archive':s.get('archive',[]),'letters':s.get('letters',[]),'ending':s.get('ending',[]),'events':s.get('events',[])[-30:]}

def clamp_res(s):
    caps=s.setdefault('caps',{})
    for k,v in list(s.setdefault('resources',{}).items()):
        cap=caps.get(k,999999 if k in ('atmosphere','temperature','biomass') else 1000)
        if v<0: s['resources'][k]=0
        elif v>cap: s['resources'][k]=cap

def advance(s, elapsed_ms, device=None):
    sec=max(0,min(MAX_RATE_SEC,elapsed_ms/1000)); before=dict(s.get('resources',{})); rr=rates(s,device)
    for k,v in rr.items(): s['resources'][k]=s['resources'].get(k,0)+v*sec
    if s['resources'].get('food',0)>30 and s['resources'].get('o2',0)>30 and sec>3600: s['resources']['population']=s['resources'].get('population',0)+min(2,sec/86400*0.08)
    clamp_res(s); beats=[]; check_milestones(s,beats); unlock_narrative(s,beats)
    gains={k:round(s['resources'].get(k,0)-before.get(k,0),2) for k in s['resources'] if abs(s['resources'].get(k,0)-before.get(k,0))>=0.01}
    count=0
    if sec>=900: count=1+int(sec//(6*3600))
    evs=draw_events(s,count)
    away=away_fragments(s,gains,evs,sec)
    gc.collect(); return {'elapsed_ms':int(sec*1000),'gains':gains,'beats':beats,'events':evs,'away':away}

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
    if a.get('counter'): s.setdefault('counters',{})[a['counter']]=s.setdefault('counters',{}).get(a['counter'],0)+1
    ev='act_'+aid+':'+action_result_id(s,aid)
    s.setdefault('events',[]).append(ev); beats=[]; unlock_narrative(s,beats)
    return {'ok':True,'event':ev,'beats':beats}

def build(s,mid):
    m=MODULES.get(mid)
    if not m: return {'ok':False,'error':'unknown module'}
    if not check_cost(s,m.get('cost',{})): return {'ok':False,'error':'insufficient'}
    pay(s,m.get('cost',{})); first=s.setdefault('modules',{}).get(mid,0)==0; s['modules'][mid]=s['modules'].get(mid,0)+1
    for k,v in m.get('caps',{}).items(): s.setdefault('caps',{})[k]=s['caps'].get(k,100)+v
    for a in m.get('unlock',[]):
        if a not in s.setdefault('unlocked_actions',[]): s['unlocked_actions'].append(a)
    beats=[]
    if first and m.get('beat'): add_beat(s,beats,m['beat'])
    check_milestones(s,beats); unlock_narrative(s,beats)
    return {'ok':True,'beats':beats}

def add_beat(s,beats,bid):
    if bid not in s.setdefault('events',[]): s['events'].append(bid)
    if bid not in beats: beats.append(bid)

def check_milestones(s,beats):
    for m in MILESTONES:
        if s.get('act',1)<m['act'] and m['cond'](s):
            s['act']=m['act']; add_beat(s,beats,m['beat'])
            if m.get('tab') and m['tab'] not in s.setdefault('unlocked_tabs',[]): s['unlocked_tabs'].append(m['tab'])
    for bid,cond in INTERNAL_BEATS:
        if cond(s) and bid not in s.setdefault('events',[]): add_beat(s,beats,bid)

def unlock_narrative(s,beats):
    act=s.get('act',1); counters=s.setdefault('counters',{})
    # Archive chains: unlock next eligible seq per strand as act/counters rise.
    for strand,count in schema.ARCHIVE_STRANDS.items():
        current=len([x for x in s.setdefault('archive',[]) if x.startswith('arc_'+strand+'_')])
        target=min(count, max(1, act*2 + counters.get('decode_count',0)//2 + counters.get('survey_count',0)//2))
        for n in range(current+1,target+1):
            cid='arc_%s_%02d'%(strand,n)
            if cid not in s['archive']: s['archive'].append(cid)
    # Recurring letters: one per sender per act gate.
    for sender in schema.SENDERS:
        for n in range(1,min(4,act)+1):
            cid='ltr_%s_%02d'%(sender,n)
            if cid not in s.setdefault('letters',[]): s['letters'].append(cid)
    # Ending sequence becomes visible in act 5.
    if act>=5:
        for e in schema.ending_entries():
            if e['id'] not in s.setdefault('ending',[]): s['ending'].append(e['id'])
    check_milestones(s,beats)

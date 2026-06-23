import json, os, machine, ubinascii
from config import SAVE_VERSION, IDENTITY_VERSION
DATA_DIR='data'; DEVICE_PATH='data/device.json'; DEVICE_BAK='data/device.bak'; SAVE_PATH='data/save.json'; SAVE_BAK='data/save.bak'
SIGNATURES=('ice','rare_metals','polymer','seeds','reactor_parts','microbes','alloy','medicine','archives')
def ensure_data_dir():
    try: os.mkdir(DATA_DIR)
    except OSError: pass
def _read_json(path):
    with open(path,'r') as f: return json.loads(f.read())
def _atomic(path,bak,obj):
    ensure_data_dir(); tmp=path+'.tmp'; data=json.dumps(obj)
    with open(tmp,'w') as f: f.write(data)
    try: os.remove(bak)
    except OSError: pass
    try: os.rename(path,bak)
    except OSError: pass
    os.rename(tmp,path)
def device_uid(): return ubinascii.hexlify(machine.unique_id()).decode()
def default_device():
    uid=device_uid(); idx=sum(bytearray(uid.encode()))%len(SIGNATURES); sig=SIGNATURES[idx]
    name='Ares '+uid[-4:].upper()
    return {'identity_version':IDENTITY_VERSION,'device_uid':uid,'signature_resource':sig,'hab_name':name,'ap_ssid':'MARS-HAB-'+name.replace(' ','-'),'ap_password':'','provisioned_at':0}
def load_device():
    ensure_data_dir()
    for p in (DEVICE_PATH, DEVICE_BAK):
        try:
            d=_read_json(p)
            if d.get('device_uid') != device_uid(): d['device_uid_warning']='uid_mismatch'
            for k,v in default_device().items(): d.setdefault(k,v)
            return d
        except Exception: pass
    d=default_device(); save_device(d); return d
def save_device(d): _atomic(DEVICE_PATH, DEVICE_BAK, d)
def fresh_save(now=0):
    return {'save_version':SAVE_VERSION,'last_seen_wall_ms':now,'created_wall_ms':now,'act':1,'legacy':0,'complete':False,'resources':{'o2':35,'power':30,'water':18,'food':12,'regolith':0,'population':6,'atmosphere':0,'temperature':0,'biomass':0},'caps':{'o2':100,'power':100,'water':80,'food':80,'regolith':300,'population':12,'atmosphere':1,'temperature':1,'biomass':1},'modules':{},'cooldowns':{},'unlocked_actions':['vent_co2','reroute_power','collect_ice','sift_regolith'],'unlocked_tabs':['hab','surface','comms'],'archive':['arc_system_memory_01'],'letters':[],'ending':[],'events':['evt_equipment_backup_boot'],'event_recent':['evt_equipment_backup_boot'],'away_recent':[],'counters':{'decode_count':0,'survey_count':0,'explore_count':0},'tends':{},'passport':{'visits':[],'tokens':0},'redeemed':[],'trade_seq':0,'rng':12345}
def migrate(s):
    if not isinstance(s,dict): return fresh_save(0)
    s.setdefault('save_version',1); s.setdefault('resources',{}); s.setdefault('caps',{}); s.setdefault('modules',{}); s.setdefault('cooldowns',{}); s.setdefault('unlocked_actions',['vent_co2']); s.setdefault('unlocked_tabs',['hab']); s.setdefault('archive',[]); s.setdefault('letters',[]); s.setdefault('ending',[]); s.setdefault('events',[]); s.setdefault('event_recent',[]); s.setdefault('away_recent',[]); s.setdefault('counters',{}); s.setdefault('tends',{}); s.setdefault('passport',{'visits':[],'tokens':0}); s.setdefault('redeemed',[]); s.setdefault('trade_seq',0); s.setdefault('last_seen_wall_ms',0); s.setdefault('act',1); s.setdefault('legacy',0); s.setdefault('complete',False); s.setdefault('rng',12345)
    s['passport'].setdefault('visits',[]); s['passport'].setdefault('tokens',0)
    s['resources'].setdefault('atmosphere',0); s['resources'].setdefault('temperature',0); s['resources'].setdefault('biomass',0)
    s['caps'].setdefault('atmosphere',1); s['caps'].setdefault('temperature',1); s['caps'].setdefault('biomass',1)
    s['counters'].setdefault('decode_count',0); s['counters'].setdefault('survey_count',0); s['counters'].setdefault('explore_count',0)
    if 'arc_boot_01' in s.get('archive',[]): s['archive'].remove('arc_boot_01')
    if not s.get('archive'): s['archive'].append('arc_system_memory_01')
    return s
def load_save():
    ensure_data_dir()
    for p in (SAVE_PATH, SAVE_BAK):
        try: return migrate(_read_json(p))
        except Exception: pass
    s=fresh_save(0); save_save(s); return s
def save_save(s): _atomic(SAVE_PATH, SAVE_BAK, s)

import json, gc
BASE='content/'
TYPE_FILE={'events':'events.json','away':'away.json','archive':'archive.json','beats':'beats.json','letters':'letters.json','ui':'ui.json','actions':'actions.json','ending':'ending.json'}
def load_type(t):
    try:
        with open(BASE+TYPE_FILE[t],'r') as f: data=json.loads(f.read())
    except Exception: data={}
    gc.collect(); return data
def get(t,cid):
    data=load_type(t); v=data.get(cid)
    if v is None: return '[STUB %s]'%cid
    if isinstance(v,dict): return v
    return v
def manifest():
    try:
        with open(BASE+'content_manifest.json','r') as f: return json.loads(f.read())
    except Exception: return {}
def validate():
    m=manifest(); missing=[]; extra=[]
    by={}
    for cid,meta in m.items(): by.setdefault(meta.get('type'),[]).append(cid)
    for t,ids in by.items():
        d=load_type(t)
        for cid in ids:
            if cid not in d: missing.append(cid)
        for cid in d:
            if cid not in m: extra.append(cid)
    return {'ok':not missing,'missing':missing,'extra':extra}

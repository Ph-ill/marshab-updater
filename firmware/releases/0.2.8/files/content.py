import json, gc
try:
    import os
    _HERE=__file__.rsplit('/',1)[0]
    BASE=_HERE+'/content/' if _HERE else 'content/'
except Exception:
    BASE='content/'
import content_schema as schema
TYPE_FILE={'events':'events.json','away':'away.json','archive':'archive.json','beats':'beats.json','letters':'letters.json','ui':'ui.json','actions':'actions.json','ending':'ending.json'}

def load_type(t):
    try:
        with open(BASE+TYPE_FILE[t],'r') as f: data=json.loads(f.read())
    except Exception: data={}
    gc.collect(); return data

def get(t,cid):
    data=load_type(t); v=data.get(cid)
    if v is None: return '[STUB %s]'%cid
    return v

def action_text(aid): return get('actions','act_'+aid)
def event_text(cid): return get('events',cid)
def away_text(cid): return get('away',cid)
def beat_text(cid): return get('beats',cid)
def archive_text(cid): return get('archive',cid)
def letter_text(cid): return get('letters',cid)
def ending_text(cid): return get('ending',cid)

def manifest():
    try:
        with open(BASE+'content_manifest.json','r') as f: return json.loads(f.read())
    except Exception: return {}

def engine_ids(): return {e['id']:e for e in schema.all_entries()}

def validate():
    m=manifest(); missing=[]; extra=[]; dead=[]; no_manifest=[]; bad=[]
    eng=engine_ids()
    for cid in eng:
        if cid not in m: no_manifest.append(cid)
    for cid in m:
        if cid not in eng: dead.append(cid)
    by={}
    for cid,meta in m.items(): by.setdefault(meta.get('type'),[]).append(cid)
    for t,ids in by.items():
        d=load_type(t)
        for cid in ids:
            if cid not in d: missing.append(cid)
        for cid in d:
            if cid not in m: extra.append(cid)
    # structural sanity: each event pool, archive strand, action, and ending sequence has entries.
    for pool in schema.POOLS:
        if not [e for e in schema.event_entries() if e.get('pool')==pool]: bad.append('empty_pool:'+pool)
    for aid in schema.ACTIONS:
        a=get('actions','act_'+aid)
        if not isinstance(a,dict) or not all(k in a for k in ('label','flavor','result_1','result_2','result_3')): bad.append('bad_action:'+aid)
    for strand,count in schema.ARCHIVE_STRANDS.items():
        seq=[e.get('seq') for e in schema.archive_entries() if e.get('strand')==strand]
        if seq != list(range(1,count+1)): bad.append('bad_archive_seq:'+strand)
    end=[e.get('seq') for e in schema.ending_entries()]
    if end != list(range(1,len(end)+1)): bad.append('bad_ending_seq')
    return {'ok':not (missing or no_manifest or dead or bad),'missing':missing,'extra':extra,'no_manifest':no_manifest,'dead_manifest':dead,'bad':bad}

def stub_report():
    found=[]; counts={}
    for t in TYPE_FILE:
        d=load_type(t); c=0
        for cid,v in d.items():
            if '[STUB' in json.dumps(v):
                c+=1
                if len(found)<20: found.append(cid)
        counts[t]=c
    return {'stub_count':sum(counts.values()),'by_type':counts,'examples':found}

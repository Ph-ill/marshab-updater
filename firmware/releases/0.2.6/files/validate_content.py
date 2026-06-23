#!/usr/bin/env python3
import json, pathlib, sys
root=pathlib.Path(__file__).parent
sys.path.insert(0,str(root))
import content_schema as schema
m=json.loads((root/'content/content_manifest.json').read_text())
missing=[]; extra=[]; no_manifest=[]; dead=[]; bad=[]
engine={e['id']:e for e in schema.all_entries()}
for cid in engine:
    if cid not in m: no_manifest.append(cid)
for cid in m:
    if cid not in engine: dead.append(cid)
for typ in sorted({v['type'] for v in m.values()}):
    p=root/'content'/f'{typ}.json'
    data=json.loads(p.read_text()) if p.exists() else {}
    wanted={k for k,v in m.items() if v['type']==typ}
    missing += sorted(wanted-set(data))
    extra += sorted(set(data)-wanted)
for pool in schema.POOLS:
    ids=[e for e in schema.event_entries() if e.get('pool')==pool]
    if not ids: bad.append('empty_pool:'+pool)
for aid in schema.ACTIONS:
    cid='act_'+aid
    if cid not in m: bad.append('missing_action_manifest:'+cid)
    p=root/'content/actions.json'; actions=json.loads(p.read_text()) if p.exists() else {}
    a=actions.get(cid,{})
    if not isinstance(a,dict) or not all(k in a for k in ['label','flavor','result_1','result_2','result_3']): bad.append('bad_action:'+cid)
for strand,count in schema.ARCHIVE_STRANDS.items():
    seq=[e.get('seq') for e in schema.archive_entries() if e.get('strand')==strand]
    if seq != list(range(1,count+1)): bad.append('bad_archive_seq:'+strand)
end=[e.get('seq') for e in schema.ending_entries()]
if end != list(range(1,len(end)+1)): bad.append('bad_ending_seq')
print(json.dumps({'ok':not (missing or no_manifest or dead or bad),'counts':{t:sum(1 for v in m.values() if v['type']==t) for t in sorted({v['type'] for v in m.values()})},'missing':missing,'extra':extra,'no_manifest':no_manifest,'dead_manifest':dead,'bad':bad},indent=2))
sys.exit(0 if not (missing or no_manifest or dead or bad) else 1)

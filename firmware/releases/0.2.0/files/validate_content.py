#!/usr/bin/env python3
import json, pathlib, sys
root=pathlib.Path(__file__).parent
m=json.loads((root/'content/content_manifest.json').read_text())
missing=[]; extra=[]
for typ in sorted({v['type'] for v in m.values()}):
    p=root/'content'/f'{typ}.json'
    data=json.loads(p.read_text()) if p.exists() else {}
    wanted={k for k,v in m.items() if v['type']==typ}
    missing += sorted(wanted-set(data))
    extra += sorted(set(data)-wanted)
print(json.dumps({'ok':not missing,'missing':missing,'extra':extra},indent=2))
sys.exit(0 if not missing else 1)

import json, ubinascii, time
ALPH='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
def checksum(s):
    n=0
    for c in s: n=(n*33+ord(c))&0xffff
    return '%04X'%n
def encode_package(state,device):
    sig=device.get('signature_resource','ice'); amt=25+state.get('act',1)*10
    state['trade_seq']=state.get('trade_seq',0)+1
    payload='%s:%d:%s:%d'%(sig,amt,device.get('device_uid','')[-6:],state['trade_seq'])
    raw=ubinascii.b2a_base64(payload.encode()).decode().strip().replace('=','')
    return 'MH-'+raw+'-'+checksum(raw)
def redeem(state,code):
    try:
        code=code.strip()
        if not code.upper().startswith('MH-'): return {'ok':False,'error':'bad code'}
        raw,chk=code[3:].rsplit('-',1)
        if checksum(raw)!=chk.upper(): return {'ok':False,'error':'checksum'}
        pad='='*((4-len(raw)%4)%4); payload=ubinascii.a2b_base64((raw+pad).encode()).decode()
        res,amt,origin,seq=payload.split(':')
        key=origin+':'+seq
        if key in state.setdefault('redeemed',[]): return {'ok':False,'error':'already redeemed'}
        state['redeemed'].append(key); state.setdefault('resources',{})[res]=state['resources'].get(res,0)+int(amt)
        p=state.setdefault('passport',{'visits':[],'tokens':0})
        p.setdefault('visits',[]); p.setdefault('tokens',0)
        first=origin not in p['visits']
        if first:
            p['visits'].append(origin); p['tokens']=p.get('tokens',0)+1
        return {'ok':True,'resource':res,'amount':int(amt),'origin':origin,'new_visit':first,'passport_visits':len(p['visits'])}
    except Exception as e: return {'ok':False,'error':'invalid'}
def tend(state,visitor='guest'):
    key=visitor[:12]; now=time.ticks_ms() if hasattr(time,'ticks_ms') else int(time.time()*1000); state.setdefault('tends',{})[key]={'until_ms':now+6*60*60*1000,'boost':0.1}
    return {'ok':True,'reward':{'unity':1},'boost':'10% production for 6h'}

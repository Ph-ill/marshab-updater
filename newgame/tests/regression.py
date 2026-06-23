#!/usr/bin/env python3
import pathlib, sys, types, binascii, json, subprocess, os, shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.modules.setdefault('machine',types.SimpleNamespace(unique_id=lambda: b'abc123'))
sys.modules.setdefault('ubinascii',binascii)
import state, sim, content, multiplayer, server

def assert_true(x,msg):
    if not x: raise AssertionError(msg)

def syntax_checks():
    files=['sim.py','state.py','server.py','content.py','multiplayer.py','main.py','config.py','validate_content.py']
    subprocess.check_call([sys.executable,'-m','py_compile']+[str(ROOT/f) for f in files])
    subprocess.check_call(['node','--check',str(ROOT/'www/app.js')])

def content_checks():
    v=content.validate(); assert_true(v.get('ok'),v)
    r=content.stub_report(); assert_true(r['stub_count']==0,r)

def build_full_spine():
    s=state.fresh_save(123456); dev=state.default_device()
    # Fund the deterministic completion path; separate economy pacing tests use offline accrual.
    s['resources'].update({'regolith':50000,'power':50000,'water':50000,'food':50000,'alloy':50000,'polymer':50000,'rare_metals':50000,'atmosphere':1,'temperature':1,'biomass':1})
    path=['solar_array','ice_well','greenhouse','fab_shop','relay_array','survey_garage','dome_segment','atmo_processor','bioreactor','thermal_mirror','airlock_protocol']
    for mid in path:
        res=sim.build(s,mid); assert_true(res['ok'],(mid,res,sim.snapshot(s,dev)))
    snap=sim.snapshot(s,dev)
    assert_true(snap['act']==5,snap)
    assert_true(snap['environment']['open_air_ready'],snap['environment'])
    assert_true('open_airlock' in snap['actions'],snap['actions'])
    res=sim.action(s,'open_airlock',now=snap['now_ms']); assert_true(res['ok'],res)
    snap=sim.snapshot(s,dev)
    assert_true(snap['complete'] and snap['legacy']==1,snap)
    assert_true(len(snap['ending'])>=12,snap['ending'])
    return s,dev

def economy_offline_checks():
    s=state.fresh_save(0); dev=state.default_device()
    s['resources'].update({'regolith':1000,'power':1000,'water':1000,'food':1000})
    for mid in ['solar_array','ice_well','greenhouse']:
        res=sim.build(s,mid); assert_true(res['ok'],(mid,res))
    before=dict(s['resources'])
    report=sim.advance(s,7*24*3600*1000,dev)
    assert_true(report['elapsed_ms']==7*24*3600*1000,report)
    assert_true(s['resources']['o2']>0 and s['resources']['food']>0 and s['resources']['water']>0,(before,s['resources'],report))
    assert_true(s['resources']['population']>=before['population'],(before,s['resources'],report))
    assert_true(s['resources']['power']<=s['caps']['power'],(s['resources'],s['caps']))
    assert_true(report['away'],report)

def pacing_checks():
    s=state.fresh_save(0); dev=state.default_device()
    s['resources'].update({'regolith':50000,'power':50000,'water':50000,'food':50000,'alloy':50000,'polymer':50000,'rare_metals':50000})
    for mid in ['solar_array','ice_well','greenhouse','fab_shop','relay_array','survey_garage','dome_segment','atmo_processor','bioreactor','thermal_mirror']:
        res=sim.build(s,mid); assert_true(res['ok'],(mid,res))
    report=sim.advance(s,30*24*3600*1000,dev)
    env=sim.environment(s)
    assert_true(env['breathability_confidence']>=30,(env,report,s['resources']))
    assert_true(s['resources']['atmosphere']<1,(env,s['resources']))
    s['resources'].update({'regolith':50000,'power':50000,'water':50000,'food':50000,'alloy':50000,'polymer':50000,'rare_metals':50000})
    for mid in ['solar_array','ice_well','greenhouse','fab_shop','relay_array','survey_garage','dome_segment','atmo_processor','bioreactor','thermal_mirror']:
        while sim.available_modules(s).get(mid,{}).get('buildable'):
            res=sim.build(s,mid); assert_true(res['ok'],(mid,res))
    sim.advance(s,30*24*3600*1000,dev)
    assert_true(sim.environment(s)['breathability_confidence']>=94,(sim.environment(s),s['resources']))

def multiplayer_checks():
    home=state.fresh_save(0); dev=state.default_device(); dev['device_uid']='origin01'; dev['signature_resource']='ice'
    other=state.fresh_save(0); base=sim.rates(other,dev)['power']
    code=multiplayer.encode_package(home,dev)
    res=multiplayer.redeem(other,code); assert_true(res['ok'],res)
    assert_true(len(other['passport']['visits'])==1,other['passport'])
    assert_true(sim.rates(other,dev)['power']>base,(base,sim.rates(other,dev)))
    assert_true(not multiplayer.redeem(other,code)['ok'],'duplicate accepted')
    tend=multiplayer.tend(home,'guest-a'); assert_true(tend['ok'],tend)

def new_game_plus_checks():
    s,dev=build_full_spine(); s['passport']={'visits':['aaaaaa','bbbbbb'],'tokens':2}; s['redeemed']=['aaaaaa:1']
    res=sim.new_game_plus(s); assert_true(res['ok'],res)
    snap=sim.snapshot(s,dev)
    assert_true(snap['act']==0 and not snap['complete'],snap)
    assert_true(snap['legacy']==1 and snap['passport_bonus']==0.04,snap)
    assert_true(s['redeemed']==['aaaaaa:1'],s['redeemed'])

def protected_payload_checks():
    for p in ROOT.rglob('__pycache__'):
        shutil.rmtree(p)
    bad=[str(p) for p in ROOT.rglob('__pycache__')]
    assert_true(not bad,bad)

def captive_portal_checks():
    for p in ('/generate_204','/gen_204','/hotspot-detect.html','/ncsi.txt','/connecttest.txt','/canonical.html','/fwlink'):
        assert_true(p in server.PORTAL,p)
    body=server.portal_body('/generate_204')
    assert_true('Mars Hab gateway' in body and '192.168.4.1' in body,body)

def main():
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    syntax_checks(); content_checks(); build_full_spine(); economy_offline_checks(); pacing_checks(); multiplayer_checks(); new_game_plus_checks(); captive_portal_checks(); protected_payload_checks()
    print(json.dumps({'ok':True,'checks':['syntax','content','full_spine','offline','pacing','multiplayer','new_game_plus','captive_portal','payload_hygiene']}))

if __name__=='__main__': main()

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
import gc, network, time
from config import AP_IP, SIM_TICK_MS, PERSIST_INTERVAL_MS
from state import load_device, load_save, save_save
import sim, server
ctx={'device':None,'state':None,'dirty':False,'last_tick':time.ticks_ms() if hasattr(time,'ticks_ms') else int(time.time()*1000)}
def start_ap(device):
    ap=network.WLAN(network.AP_IF); ssid=device.get('ap_ssid') or ('MARS-HAB-'+device.get('hab_name','Crew'))
    pwd=device.get('ap_password','') or ''
    try: ap.active(False)
    except Exception: pass
    if pwd:
        try: ap.config(essid=ssid,password=pwd)
        except Exception as e: print('secured ap failed, open fallback',e); pwd=''
    if not pwd:
        for kw in ({'essid':ssid,'password':'','authmode':0},{'essid':ssid,'security':0},{'essid':ssid}):
            try: ap.config(**kw); break
            except Exception: pass
    ap.active(True)
    try: ap.ifconfig((AP_IP,'255.255.255.0',AP_IP,AP_IP))
    except Exception as e: print('ifconfig warning',e)
    print('Mars Hab AP',ssid,ap.ifconfig()); return ap
async def sim_loop():
    while True:
        await asyncio.sleep_ms(SIM_TICK_MS)
        now=time.ticks_ms() if hasattr(time,'ticks_ms') else int(time.time()*1000); dt=time.ticks_diff(now,ctx['last_tick']) if hasattr(time,'ticks_diff') else now-ctx['last_tick']; ctx['last_tick']=now
        sim.advance(ctx['state'], dt, ctx['device']); ctx['dirty']=True; gc.collect()
async def persist_loop():
    while True:
        await asyncio.sleep_ms(PERSIST_INTERVAL_MS)
        if ctx.get('dirty'):
            save_save(ctx['state']); ctx['dirty']=False; print('save persisted')
async def task_guard(name, coro):
    try:
        await coro
    except Exception as e:
        print(name, 'stopped', e)
async def main():
    ctx['device']=load_device(); ctx['state']=load_save(); start_ap(ctx['device'])
    server.set_context(ctx)
    # Keep HTTP alive even if optional captive-DNS setup fails.
    asyncio.create_task(task_guard('http', server.http_server()))
    asyncio.create_task(task_guard('dns', server.dns_server()))
    asyncio.create_task(task_guard('sim', sim_loop()))
    asyncio.create_task(task_guard('persist', persist_loop()))
    while True:
        await asyncio.sleep(3600)
try: asyncio.run(main())
finally:
    try: asyncio.new_event_loop()
    except Exception: pass

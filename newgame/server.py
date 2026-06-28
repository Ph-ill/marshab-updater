try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
import socket, json, gc, os
from config import AP_IP, HTTP_PORT, DNS_PORT, MAX_CATCHUP_MS, FIRMWARE_VERSION
from state import save_save, save_device, fresh_save
import sim, content, multiplayer
CTX=None
def set_context(c):
    global CTX; CTX=c
def js(obj): return json.dumps(obj,separators=(',',':'))
def mime(path):
    if path.endswith('.html'): return 'text/html; charset=utf-8'
    if path.endswith('.js'): return 'application/javascript; charset=utf-8'
    if path.endswith('.css'): return 'text/css; charset=utf-8'
    if path.endswith('.json'): return 'application/json'
    if path.endswith('.ico'): return 'image/x-icon'
    return 'text/plain; charset=utf-8'
async def send(w,status,ctype,body,extra=''):
    if isinstance(body,str): body=body.encode()
    reason={200:'OK',204:'No Content',302:'Found',404:'Not Found',500:'Error'}.get(status,'OK')
    head='HTTP/1.0 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\nConnection: close\r\n%s\r\n'%(status,reason,ctype,len(body),extra)
    w.write(head.encode()+body); await w.drain()
def portal_body(path):
    return ('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Mars Hab Gateway</title><style>'
            'body{margin:0;padding:22px;background:#160f12;color:#ffd99c;font:16px sans-serif}'
            '.card{max-width:390px;margin:42px auto;padding:22px;border:1px solid #c9823a;border-radius:18px;background:#2a1818;text-align:center}'
            'h1{font-size:24px;margin:0 0 12px;color:#ffe4ad;letter-spacing:.06em}'
            'p{color:#d5a46d;line-height:1.45}.btn{display:block;margin:18px 0;padding:14px;border-radius:14px;background:#ffb84a;color:#1d120b;text-decoration:none;font-weight:bold}'
            '.ip{font:13px monospace;color:#b98f62}'
            '</style></head><body><main class="card"><h1>MARS HAB GATEWAY</h1>'
            '<p>Mars Hab gateway: your MarsHab device is ready.</p>'
            '<a class="btn" href="http://%s/">Open colony control</a>'
            '<div class="ip">http://%s/</div></main></body></html>')%(AP_IP,AP_IP)

async def send_portal(w,path):
    # Be deliberately obvious to OS captive-portal detectors. Returning a real
    # HTML body instead of 204/no-content is what makes phones open their sign-in
    # sheet. Avoid relying on redirects; some mobile stacks cache or suppress
    # them on repeat joins.
    await send(w,200,'text/html; charset=utf-8',portal_body(path))
def file_bytes(path):
    with open(path,'rb') as f: return f.read()
async def read_req(r):
    line=await r.readline()
    if not line: return None
    method,path,_=line.decode().split(' ',2); length=0
    while True:
        h=await r.readline()
        if h in (b'\r\n',b'\n',b''): break
        hs=h.decode().lower()
        if hs.startswith('content-length:'): length=int(hs.split(':',1)[1].strip())
    body=await r.read(length) if length else b''
    return method,path.split('?',1)[0],body
def full_snapshot(extra=None):
    d=sim.snapshot(CTX['state'],CTX['device'])
    if extra: d.update(extra)
    return d
def parse_body(body):
    try: return json.loads(body.decode() if body else '{}')
    except Exception: return {}
async def api(path,method,body):
    s=CTX['state']; dev=CTX['device']; data=parse_body(body)
    if path=='/api/sync' and method=='POST':
        now=int(data.get('now') or 0); last=int(s.get('last_seen_wall_ms') or 0)
        report={'elapsed_ms':0,'gains':{},'beats':[],'away':[]}
        if last and now>last: report=sim.advance(s,min(MAX_CATCHUP_MS,now-last),dev)
        if now: s['last_seen_wall_ms']=now
        save_save(s); CTX['dirty']=False
        return full_snapshot({'away_report':report,'content_check':content.validate()})
    if path=='/api/state' and method=='GET': return full_snapshot()
    if path=='/api/reset' and method=='POST':
        now=int(data.get('now') or 0)
        CTX['state']=fresh_save(now)
        save_save(CTX['state']); CTX['dirty']=False
        return full_snapshot({'result':{'ok':True,'reset':True}})
    if path=='/api/diagnostics' and method=='GET':
        return {'ok':True,'firmware_version':FIRMWARE_VERSION,'content_check':content.validate(),'stub_report':content.stub_report(),'device':dev,'save_version':s.get('save_version'),'act':s.get('act'),'tabs':s.get('unlocked_tabs'),'actions':s.get('unlocked_actions')}
    if path=='/api/action' and method=='POST':
        if data.get('action_id')=='build': res=sim.build(s,data.get('module_id'))
        elif data.get('action_id')=='new_game_plus': res=sim.new_game_plus(s)
        else: res=sim.action(s,data.get('action_id'))
        if res.get('ok'): save_save(s); CTX['dirty']=False
        return full_snapshot({'result':res})
    if path=='/api/trade/package' and method=='GET': return {'ok':True,'code':multiplayer.encode_package(s,dev)}
    if path=='/api/trade/redeem' and method=='POST':
        res=multiplayer.redeem(s,data.get('code','')); save_save(s); return full_snapshot({'result':res})
    if path=='/api/tend' and method=='POST':
        res=multiplayer.tend(s,data.get('visitor','guest')); save_save(s); return full_snapshot({'result':res})
    if path.startswith('/api/content/') and method=='GET': return content.load_type(path.rsplit('/',1)[-1])
    if path=='/api/provision' and method=='POST':
        for k in ('hab_name','signature_resource','ap_ssid','ap_password'):
            if k in data: dev[k]=data[k]
        save_device(dev); return {'ok':True,'device':dev}
    return {'ok':False,'error':'not_found'}
PORTAL=('/generate_204','/gen_204','/mobile/status.php','/connectivity-check.html','/hotspot-detect.html','/library/test/success.html','/ncsi.txt','/connecttest.txt','/success.txt','/redirect','/canonical.html','/chat','/fwlink','/kindle-wifi/wifiredirect.html','/check_network_status.txt')
async def handle(r,w):
    try:
        req=await read_req(r)
        if not req: return
        method,path,body=req
        if path in PORTAL: await send_portal(w,path)
        elif path.startswith('/api/'):
            await send(w,200,'application/json',js(await api(path,method,body)))
        else:
            p='www/index.html' if path=='/' else 'www/'+path.lstrip('/')
            if '..' in p: raise OSError
            try:
                await send(w,200,mime(p),file_bytes(p))
            except OSError:
                await send_portal(w,path)
    except Exception as e:
        try: await send(w,500,'application/json',js({'ok':False,'error':str(e)}))
        except Exception: pass
    finally:
        try: await w.wait_closed()
        except Exception: pass
        gc.collect()
async def http_server():
    srv=await asyncio.start_server(handle,'0.0.0.0',HTTP_PORT); print('http',HTTP_PORT)
    while True: await asyncio.sleep(3600)
def dns_response(data):
    if len(data) < 12:
        return None
    end = 12
    # Walk the QNAME to the end of the first question.
    while end < len(data) and data[end] != 0:
        end += data[end] + 1
    if end + 5 > len(data):
        return None
    question = data[12:end + 5]
    ip = bytes(int(x) for x in AP_IP.split('.'))
    return (data[:2] + b'\x81\x80' + b'\x00\x01' + b'\x00\x01' +
            b'\x00\x00\x00\x00' + question +
            b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04' + ip)
async def dns_server():
    try:
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.setblocking(False); sock.bind(('0.0.0.0',DNS_PORT)); print('dns',DNS_PORT)
    except Exception as e:
        print('dns disabled', e)
        while True: await asyncio.sleep(3600)
    while True:
        try:
            data,addr=sock.recvfrom(512)
            resp=dns_response(data)
            if resp: sock.sendto(resp,addr)
        except OSError: await asyncio.sleep_ms(20)

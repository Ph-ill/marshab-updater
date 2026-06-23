#!/usr/bin/env python3
import json, mimetypes, pathlib, sys, types, binascii
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.modules.setdefault('machine',types.SimpleNamespace(unique_id=lambda: b'abc123'))
sys.modules.setdefault('ubinascii',binascii)
import state, sim, content, multiplayer
WWW=ROOT/'www'; CONTENT=ROOT/'content'
S=state.fresh_save(0); DEV=state.default_device(); DEV['hab_name']='Regression Mock'; DEV['signature_resource']='ice'
S['resources'].update({'regolith':5000,'power':5000,'water':5000,'food':5000,'alloy':5000,'polymer':5000,'rare_metals':5000})

def snapshot(extra=None):
    d=sim.snapshot(S,DEV)
    if extra: d.update(extra)
    return d
class H(BaseHTTPRequestHandler):
    def sendb(self,code,ctype,body):
        if isinstance(body,str): body=body.encode()
        self.send_response(code); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def sendj(self,obj): self.sendb(200,'application/json',json.dumps(obj,separators=(',',':')))
    def do_GET(self):
        p=self.path.split('?',1)[0]
        if p=='/api/state': return self.sendj(snapshot())
        if p=='/api/diagnostics': return self.sendj({'ok':True,'firmware_version':'mock','content_check':content.validate(),'stub_report':content.stub_report(),'device':DEV,'save_version':S.get('save_version'),'act':S.get('act'),'tabs':S.get('unlocked_tabs'),'actions':S.get('unlocked_actions')})
        if p=='/api/trade/package': return self.sendj({'ok':True,'code':multiplayer.encode_package(S,DEV)})
        if p.startswith('/api/content/'):
            t=p.rsplit('/',1)[-1]; return self.sendb(200,'application/json',(CONTENT/(t+'.json')).read_text())
        f=WWW/'index.html' if p=='/' else WWW/p.lstrip('/')
        if not f.exists() or '..' in p: return self.sendb(404,'text/plain','not found')
        self.sendb(200,mimetypes.guess_type(str(f))[0] or 'text/plain',f.read_bytes())
    def do_POST(self):
        p=self.path.split('?',1)[0]; length=int(self.headers.get('content-length','0') or '0'); data=json.loads(self.rfile.read(length) or b'{}')
        if p=='/api/sync': return self.sendj(snapshot({'away_report':sim.advance(S,0,DEV),'content_check':content.validate()}))
        if p=='/api/action':
            if data.get('action_id')=='build': res=sim.build(S,data.get('module_id'))
            elif data.get('action_id')=='new_game_plus': res=sim.new_game_plus(S)
            else: res=sim.action(S,data.get('action_id'),now=sim.now_ms())
            return self.sendj(snapshot({'result':res}))
        if p=='/api/trade/redeem': return self.sendj(snapshot({'result':multiplayer.redeem(S,data.get('code',''))}))
        if p=='/api/tend': return self.sendj(snapshot({'result':multiplayer.tend(S,data.get('visitor','guest'))}))
        return self.sendj({'ok':False,'error':'not_found'})
    def log_message(self,*a): pass
if __name__=='__main__':
    port=int(sys.argv[1]) if len(sys.argv)>1 else 8768
    print('sim mock',port,flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),H).serve_forever()

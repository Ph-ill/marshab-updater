
# MarsHab Pico W MicroPython firmware entrypoint.
# Starts a WiFi access point, catch-all DNS for captive portal behaviour,
# serves index/assets, and implements the MarsHab JSON API.

import json
import time
import network
import socket
import select
try:
    import uos as os
except ImportError:
    import os
from hab import Hab

AP_IP = '192.168.4.1'
HTTP_PORT = 80
DNS_PORT = 53
MAX_BODY = 65536

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.avif': 'image/avif',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    '.css': 'text/css; charset=utf-8',
}

STATUS = {
    200: 'OK', 302: 'Found', 400: 'Bad Request', 401: 'Unauthorized',
    403: 'Forbidden', 404: 'Not Found', 413: 'Payload Too Large',
    429: 'Too Many Requests', 500: 'Internal Server Error'
}

class FileStorage:
    def read(self, name):
        try:
            with open(name, 'rb') as f:
                return f.read()
        except OSError:
            return None
    def write(self, name, data):
        tmp = name + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        try:
            os.remove(name)
        except OSError:
            pass
        try:
            os.rename(tmp, name)
        except AttributeError:
            # Some ports lack rename over existing files; fallback already removed target.
            os.rename(tmp, name)


def load_config():
    defaults = {'habId':'hab_demo','ownerName':'Crew','pin':'0000','ssid':'MarsHab-Crew','password':''}
    try:
        with open('config.json','r') as f:
            cfg = json.loads(f.read())
        defaults.update(cfg)
    except Exception as e:
        print('config load failed, using defaults', e)
    return defaults


def start_ap(cfg):
    ap = network.WLAN(network.AP_IF)
    ssid = cfg.get('ssid','MarsHab')
    password = cfg.get('password','') or ''
    try:
        ap.active(False)
    except Exception:
        pass
    if password and len(password) >= 8:
        try:
            # Pico W MicroPython infers secured AP mode from password.
            # Avoid AUTH_* constants; they vary by firmware build.
            ap.config(essid=ssid, password=password)
        except Exception as e:
            print('password AP config failed, falling back to open AP', e)
            password = ''
    if not password:
        try:
            ap.config(essid=ssid)
        except Exception:
            pass
    ap.active(True)
    try:
        ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, AP_IP))
    except Exception as e:
        print('ap ifconfig warning', e)
    # Wait briefly for AP activation.
    for _ in range(30):
        if ap.active():
            break
        time.sleep_ms(100)
    print('MarsHab AP:', ssid, 'secured' if password else 'open', ap.ifconfig())
    return ap

def make_http_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', HTTP_PORT))
    s.listen(4)
    s.setblocking(False)
    return s


def make_dns_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', DNS_PORT))
    s.setblocking(False)
    return s


def ext(path):
    i = path.rfind('.')
    return path[i:] if i >= 0 else ''


def safe_path(url_path):
    path = url_path.split('?', 1)[0]
    if path == '/' or path == '/index.html':
        return 'index.html'
    if path == '/favicon.ico':
        return 'assets/favicon.ico'
    if path.startswith('/assets/'):
        rel = path[1:]
        if '..' not in rel:
            return rel
    if path == '/gift.mjs':
        return 'gift.mjs'
    return None


def send_head(c, status, ctype='text/plain; charset=utf-8', length=0, extra=''):
    reason = STATUS.get(status, 'OK')
    head = 'HTTP/1.0 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\nCache-Control: no-store\r\n%s\r\n' % (status, reason, ctype, length, extra)
    send_all(c, head.encode())


def send_all(c, data):
    view = memoryview(data)
    while view:
        sent = c.send(view)
        if sent is None:
            sent = len(view)
        view = view[sent:]


def send_bytes(c, status, ctype, data):
    send_head(c, status, ctype, len(data))
    if data:
        send_all(c, data)


def send_redirect(c, location):
    body = b''
    extra = 'Location: %s\r\n' % location
    send_head(c, 302, 'text/plain; charset=utf-8', len(body), extra)


def send_json(c, status, obj):
    send_bytes(c, status, 'application/json; charset=utf-8', json.dumps(obj, separators=(',',':')).encode())


def send_file(c, fs_path):
    try:
        size = os.stat(fs_path)[6]
        ctype = MIME.get(ext(fs_path), 'application/octet-stream')
        send_head(c, 200, ctype, size, 'Cache-Control: max-age=86400\r\n')
        with open(fs_path, 'rb') as f:
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                send_all(c, chunk)
    except OSError:
        # Captive portal fallback: unknown non-API paths show the gateway/game page.
        if fs_path != 'index.html':
            send_file(c, 'index.html')
        else:
            send_json(c, 404, {'error':'not_found'})


def parse_request(c):
    c.settimeout(3)
    data = b''
    while b'\r\n\r\n' not in data and len(data) < 4096:
        part = c.recv(512)
        if not part:
            break
        data += part
    if not data:
        return None
    head, _, rest = data.partition(b'\r\n\r\n')
    lines = head.decode('utf-8','replace').split('\r\n')
    first = lines[0].split()
    if len(first) < 2:
        return None
    method, path = first[0], first[1]
    headers = {}
    for line in lines[1:]:
        if ':' in line:
            k,v = line.split(':',1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get('content-length','0') or '0')
    if n > MAX_BODY:
        return method, path, headers, 'too_large'
    body = rest
    while len(body) < n:
        part = c.recv(n-len(body))
        if not part:
            break
        body += part
    parsed = None
    if n:
        try:
            parsed = json.loads(body[:n].decode('utf-8'))
        except Exception:
            parsed = 'bad_json'
    return method, path, headers, parsed


def handle_http(c, hab):
    try:
        req = parse_request(c)
        if not req:
            return
        method, path, headers, body = req
        base_path = path.split('?',1)[0]
        if body == 'too_large':
            send_json(c, 413, {'error':'body_too_large'}); return
        if body == 'bad_json':
            send_json(c, 400, {'error':'bad_json'}); return
        # Android/iOS/Windows captive-portal probes: redirect to the gateway page.
        captive_paths = ('/generate_204','/gen_204','/hotspot-detect.html','/library/test/success.html','/ncsi.txt','/connecttest.txt')
        if method == 'GET' and base_path in captive_paths:
            send_redirect(c, 'http://' + AP_IP + '/'); return
        if base_path.startswith('/api/'):
            auth = headers.get('authorization','')
            token = auth[7:] if auth.lower().startswith('bearer ') else None
            status, payload = hab.handle(method, base_path, body, token)
            send_json(c, status, payload)
            return
        fs = safe_path(base_path)
        if method == 'GET' and fs:
            send_file(c, fs); return
        if method == 'GET':
            send_file(c, 'index.html'); return
        send_json(c, 404, {'error':'not_found'})
    except Exception as e:
        print('http error', e)
        try:
            send_json(c, 500, {'error':'server_error'})
        except Exception:
            pass
    finally:
        try:
            c.close()
        except Exception:
            pass


def handle_dns(sock):
    try:
        data, addr = sock.recvfrom(512)
        if len(data) < 12:
            return
        tid = data[:2]
        flags = b'\x81\x80'
        qdcount = data[4:6]
        ancount = qdcount
        header = tid + flags + qdcount + ancount + b'\x00\x00\x00\x00'
        # Question starts at byte 12 and ends after zero label + qtype/qclass.
        i = 12
        while i < len(data) and data[i] != 0:
            i += data[i] + 1
        if i + 5 > len(data):
            return
        question = data[12:i+5]
        answer = b'\xc0\x0c' + b'\x00\x01\x00\x01' + b'\x00\x00\x00\x3c' + b'\x00\x04' + bytes([192,168,4,1])
        sock.sendto(header + question + answer, addr)
    except Exception as e:
        print('dns error', e)


def main():
    cfg = load_config()
    start_ap(cfg)
    hab = Hab(FileStorage(), config=cfg)
    http = make_http_socket()
    try:
        dns = make_dns_socket()
    except Exception as e:
        print('DNS captive portal disabled:', e)
        dns = None
    print('MarsHab ready: connect to SSID %r then open http://%s/' % (cfg.get('ssid'), AP_IP))
    while True:
        sockets = [http] + ([dns] if dns else [])
        readable, _, _ = select.select(sockets, [], [], 0.2)
        for s in readable:
            if s is http:
                try:
                    c, addr = http.accept()
                    handle_http(c, hab)
                except Exception as e:
                    print('accept/http error', e)
            elif dns and s is dns:
                handle_dns(dns)

main()

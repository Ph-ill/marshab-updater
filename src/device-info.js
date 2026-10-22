// What is on the board: MicroPython runtime and board, the installed Long Voyage version (version.json),
// and this ship's settings (data/ship.json).

function jsonReadSnippet(path){
  return `
try:
    with open(${JSON.stringify(path)}, 'r') as f:
        print(f.read())
except OSError:
    print('null')
`;
}

export function runtimeSnippet(){
  return `
import sys, os, json
try:
    b = sys.implementation._build
except AttributeError:
    b = ''
v = sys.implementation.version
try:
    s = os.statvfs('/')
    fs = [s[0] * s[2], s[0] * s[3]]
except Exception:
    fs = None
try:
    with open('main.py') as f:
        head = f.read(240)
except Exception:
    head = ''
try:
    root = sorted(os.listdir('/'))
except Exception:
    root = []
print(json.dumps({'mpy': '%d.%d.%d' % (v[0], v[1], v[2]), 'machine': os.uname().machine, 'build': b, 'fs': fs, 'root': root, 'mainHead': head}))
`;
}

export async function readJsonFile(device, path){
  const { stdout } = await device.exec(jsonReadSnippet(path), { timeoutMs: 8000 });
  const text = stdout.trim();
  if(!text || text === 'null') return null;
  try{
    return JSON.parse(text);
  }catch(err){
    err.message = `could not parse ${path}: ${err.message}`;
    err.rawText = text;
    throw err;
  }
}

async function readRuntime(device){
  try{
    const { stdout } = await device.exec(runtimeSnippet(), { timeoutMs: 8000 });
    return JSON.parse(stdout.trim());
  }catch(_err){
    return null;
  }
}

export function boardFromRuntime(runtime){
  if(!runtime) return null;
  if(runtime.build) return runtime.build;
  const m = runtime.machine || '';
  if(/Pico 2 W/i.test(m)) return 'RPI_PICO2_W';
  if(/Pico W/i.test(m)) return 'RPI_PICO_W';
  if(/RP2350/.test(m)) return 'RPI_PICO2';
  if(/RP2040/.test(m)) return 'RPI_PICO';
  return null;
}

// The coex bench test shipped before version.json existed; recognise it by the first line of main.py.
const COEX_FINGERPRINT = 'coexistence soak test';
// Files a blank MicroPython board may already have; anything else belongs to some other project.
const STOCK_FILES = new Set(['boot.py', 'data', 'lib']);

export function firmwareKind(info){
  if(info?.version?.project === 'LongVoyage') return 'long-voyage';
  if((info?.runtime?.mainHead || '').includes(COEX_FINGERPRINT)) return 'long-voyage';
  const root = info?.runtime?.root || [];
  return root.some(name => !STOCK_FILES.has(name)) ? 'other' : 'empty';
}

export async function readDeviceInfo(device){
  const runtime = await readRuntime(device);
  const version = await readJsonFile(device, 'version.json').catch(() => null);
  const ship = await readJsonFile(device, 'data/ship.json').catch(() => null);
  const info = { version, ship, runtime, board: boardFromRuntime(runtime) };
  info.kind = firmwareKind(info);
  return info;
}

export function summarizeDeviceInfo(info){
  const kind = info.kind || firmwareKind(info);
  const version = info.version?.project === 'LongVoyage'
    ? info.version.version
    : kind === 'long-voyage' ? 'coex test (hand-copied)' : kind === 'empty' ? 'nothing installed' : 'other firmware';
  const runtime = info.runtime ? `MicroPython ${info.runtime.mpy}` : 'unknown';
  const ship = info.ship;
  const name = ship ? `${ship.ship_name || 'ship'} · #${ship.ship_id}${ship.role ? ` · role ${ship.role}` : ''}` : 'not set';
  const fs = info.runtime?.fs ? `${Math.round(info.runtime.fs[1] / 1024)} KB free of ${Math.round(info.runtime.fs[0] / 1024)} KB` : '—';
  return { version, runtime, name, board: info.board || 'unknown', fs, kind };
}

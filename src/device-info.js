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
try:
    import machine, binascii
    uid = binascii.hexlify(machine.unique_id()).decode()
except Exception:
    uid = None
try:
    import lvfrozen
    fz = {'id': lvfrozen.ID, 'version': lvfrozen.VERSION, 'core': lvfrozen.CORE,
          'board': list(getattr(lvfrozen, 'BOARD', ())), 'pack': getattr(lvfrozen, 'PACK', None)}
except Exception:
    fz = None
try:
    lvx = sorted(os.listdir('lvx'))
except Exception:
    lvx = []
print(json.dumps({'mpy': '%d.%d.%d' % (v[0], v[1], v[2]), 'machine': os.uname().machine, 'build': b, 'fs': fs, 'root': root, 'mainHead': head, 'uid': uid, 'frozen': fz, 'lvx': lvx}))
`;
}

// The game firmware (game/tools/build_firmware.sh) has the game core frozen in and says so in
// its frozen lvfrozen module; files in /lvx override single core modules. Same wording as the
// board's own selftest line (game/lv/__init__.py describe()).
export function overridesOf(runtime){
  const names = [];
  for(const f of runtime?.lvx || []){
    const m = /^([a-z_][a-z0-9_]*)\.(mpy|py)$/.exec(f);
    if(m && !m[1].startsWith('_') && !names.includes(m[1])) names.push(m[1]);
  }
  return names;
}

// lv-core 0.2.0+ froze the board modules and the pack too: a /<module>.py|.mpy or /pack.bin
// found on the board runs instead of the frozen one (a hotfix, or a leftover to reinstall).
export function boardFilesOf(runtime){
  const fz = runtime?.frozen;
  const root = runtime?.root || [];
  const out = (fz?.board || []).filter(m => root.includes(`${m}.py`) || root.includes(`${m}.mpy`));
  if(fz?.pack && root.includes('pack.bin')) out.push('pack.bin');
  return out;
}

export function describeFirmware(runtime){
  const fz = runtime?.frozen;
  if(!fz) return 'stock MicroPython (no frozen game core)';
  const base = `frozen ${fz.id} ${fz.version} (core ${fz.core})`;
  if((runtime.root || []).includes('lv')) return `${base} HIDDEN by a /lv directory: reinstall to remove it`;
  const board = fz.board?.length ? `, board files: [${boardFilesOf(runtime).join(', ')}]` : '';
  return `${base}, overrides: [${overridesOf(runtime).join(', ')}]${board}`;
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
  const info = { version, ship, runtime, board: boardFromRuntime(runtime), uid: runtime?.uid || null };
  info.kind = firmwareKind(info);
  return info;
}

export function summarizeDeviceInfo(info){
  const kind = info.kind || firmwareKind(info);
  const version = info.version?.project === 'LongVoyage'
    ? info.version.version
    : kind === 'long-voyage' ? 'coex test (hand-copied)' : kind === 'empty' ? 'nothing installed' : 'other firmware';
  const runtime = info.runtime
    ? `MicroPython ${info.runtime.mpy}${info.runtime.frozen ? ` · game firmware: ${describeFirmware(info.runtime)}` : ''}`
    : 'unknown';
  const ship = info.ship;
  const name = ship ? `${ship.ship_name || 'ship'} · #${ship.ship_id}${ship.role ? ` · role ${ship.role}` : ''}` : 'not set';
  const fs = info.runtime?.fs ? `${Math.round(info.runtime.fs[1] / 1024)} KB free of ${Math.round(info.runtime.fs[0] / 1024)} KB` : '—';
  const board = `${info.board || 'unknown'}${info.uid ? ` · id ${info.uid}` : ''}`;
  return { version, runtime, name, board, fs, kind, firmware: info.runtime ? describeFirmware(info.runtime) : null };
}

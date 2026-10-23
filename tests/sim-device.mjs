// A fake board for headless tests: runs each raw-REPL snippet in CPython inside a temp "flash" dir.
// CPython is close enough to MicroPython for file I/O, json, binascii, hashlib; a shim fills the gaps.
import { spawnSync } from 'node:child_process';

const SHIM = `
import os, sys
if not hasattr(os, 'ilistdir'):
    def _il(p='.'):
        for n in os.listdir(p):
            yield (n, 0x4000 if os.path.isdir(os.path.join(p, n)) else 0x8000, 0)
    os.ilistdir = _il
sys.modules['uos'] = os
import binascii, hashlib, json
sys.modules['ubinascii'] = binascii; sys.modules['uhashlib'] = hashlib; sys.modules['ujson'] = json
class _U:
    sysname='rp2'; nodename='rp2'; release='1.29.0'; version='v1.29.0 on 2026-08-24'
    machine='Raspberry Pi Pico W with RP2040'
os.uname = lambda: _U
import types as _t
_impl = _t.SimpleNamespace(**vars(sys.implementation))
_impl.version = (1, 29, 0, ''); _impl._build = 'RPI_PICO_W'
sys.implementation = _impl
import types as _t2
_m = _t2.ModuleType('machine')
# unique_id: 8 bytes like the RP2 flash id; a test can give each sim board its own via SIM_UID
_m.unique_id = lambda: bytes.fromhex(os.environ.get('SIM_UID', 'e6614c311b2a3d2f'))
sys.modules['machine'] = _m
# SIM_FROZEN=id:version:core makes it the game firmware (a frozen lvfrozen module).
if os.environ.get('SIM_FROZEN'):
    _f = _t2.ModuleType('lvfrozen')
    _f.ID, _f.VERSION, _f.CORE = os.environ['SIM_FROZEN'].split(':')
    sys.modules['lvfrozen'] = _f
_ld, _sv = os.listdir, os.statvfs
os.listdir = lambda p='.': _ld('.' if p in ('/', '') else p)
os.statvfs = lambda p='.': _sv('.')
`;

export class SimDevice {
  constructor(root, { uid = 'e6614c311b2a3d2f', frozen = '' } = {}){ this.root = root; this.uid = uid; this.frozen = frozen; this.execs = 0; this.resets = 0; }
  async exec(code, _opts = {}){
    this.execs++;
    const r = spawnSync('python3', ['-c', SHIM + '\n' + code], { cwd: this.root, encoding: 'utf8', env: { ...process.env, SIM_UID: this.uid, SIM_FROZEN: this.frozen } });
    if(r.status !== 0) throw new Error(`device exec failed: ${r.stderr.trim().split('\n').pop()}`);
    return { stdout: r.stdout, stderr: r.stderr };
  }
  async firmwareInstallReset(){ this.resets++; }
  async hardReset(){ this.resets++; }
}

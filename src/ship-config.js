// Per-ship identity for The Long Voyage, stored on the board at data/ship.json.
// data/ is never touched by firmware updates, so this survives every release.
export const SHIP_CONFIG_PATH = 'data/ship.json';

export function defaultShipName(id, pattern = 'Starship-{nn}'){
  return pattern.replace('{nn}', String(id).padStart(2, '0')).replace('{n}', String(id));
}

// Hotspot: the firmware default is WPA2 (config.AP_PASSWORD). A blank password here keeps that default;
// a new password must be 8-63 characters; an open network has to be asked for explicitly.
export function validateShipConfig({ ship_id, ship_name, hotspot_password, hotspot_open, role }, { count = 8, roles = [] } = {}){
  const id = Number.parseInt(ship_id, 10);
  if(!Number.isInteger(id) || id < 1 || id > count) throw new Error(`ship number must be 1-${count}`);
  const name = String(ship_name || '').trim() || defaultShipName(id);
  if(new TextEncoder().encode(name).length > 24) throw new Error('ship name must be 24 bytes or less (it is also the Bluetooth name)');
  if(/[\x00-\x1f\x7f"\\]/.test(name)) throw new Error('ship name cannot contain control characters, quotes or backslashes');
  const open = !!hotspot_open;
  const pw = open ? '' : String(hotspot_password || '');
  if(pw && (pw.length < 8 || pw.length > 63)) throw new Error('hotspot password must be 8-63 characters (leave blank to keep the WPA2 default)');
  if(/[\x00-\x1f\x7f]/.test(pw)) throw new Error('hotspot password cannot contain control characters');
  const r = String(role || '').toUpperCase();
  if(r && !roles.includes(r)) throw new Error(`bench role must be one of ${roles.join(', ') || '(none for this release)'}`);
  const cfg = { schema: 2, ship_id: id, ship_name: name, role: r || null, hotspot_open: open };
  if(pw) cfg.hotspot_password = pw;
  return cfg;
}

// The coex firmware names its hotspot COEX-<n>: role A -> 0, role B -> 1, and with no role it keeps
// its built-in SHIP_ID 0. So "no role" and "A" broadcast the same name.
export const HOTSPOT_PREFIX = 'COEX-';
export function hotspotForRole(role, roles = ['A', 'B']){
  const i = roles.indexOf(String(role || '').toUpperCase());
  return `${HOTSPOT_PREFIX}${i < 0 ? 0 : i}`;
}

// Bench convention: role A is ship 1, role B is ship 2 (null for no role or an unknown one).
export function shipNumberForRole(role, roles = ['A', 'B']){
  const i = roles.indexOf(String(role || '').toUpperCase());
  return i < 0 ? null : i + 1;
}

export function hotspotSummary(cfg){
  if(!cfg) return 'firmware default (WPA2)';
  if(cfg.hotspot_open) return 'open network';
  return cfg.hotspot_password ? 'WPA2, custom password' : 'WPA2, firmware default password';
}

export async function writeShipConfig(device, cfg){
  const payload = JSON.stringify({ ...cfg, updated_at: new Date().toISOString() });
  const code = `
try:
    import uos as os
except ImportError:
    import os
import json
payload = ${JSON.stringify(payload)}
json.loads(payload)
try:
    os.mkdir('data')
except OSError:
    pass
with open('data/ship.tmp', 'w') as f:
    f.write(payload)
with open('data/ship.tmp') as f:
    json.loads(f.read())
try:
    os.remove('data/ship.bak')
except OSError:
    pass
try:
    os.rename('data/ship.json', 'data/ship.bak')
except OSError:
    pass
os.rename('data/ship.tmp', 'data/ship.json')
print('ship-ok')
`;
  const { stdout } = await device.exec(code, { timeoutMs: 12000 });
  if(!stdout.includes('ship-ok')) throw new Error('device did not confirm ship config write');
  return JSON.parse(payload);
}

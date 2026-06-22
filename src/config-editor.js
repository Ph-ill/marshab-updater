function pyString(value){
  return JSON.stringify(value);
}

function validateSsid(ssid){
  const clean = String(ssid || '').trim();
  const bytes = new TextEncoder().encode(clean).length;
  if(!clean) throw new Error('SSID is required');
  if(bytes > 32) throw new Error('SSID must be 32 bytes or less');
  if(/[\x00-\x1f\x7f]/.test(clean)) throw new Error('SSID cannot contain control characters');
  return clean;
}

function validatePassword(password){
  const clean = String(password || '');
  if(!clean) return '';
  if(clean.length < 8 || clean.length > 63) throw new Error('WiFi password must be blank or 8–63 characters');
  if(/[\x00-\x1f\x7f]/.test(clean)) throw new Error('WiFi password cannot contain control characters');
  return clean;
}

export function validateWifiConfig({ ssid, password }){
  const cleanPassword = validatePassword(password);
  return { ssid: validateSsid(ssid), password: cleanPassword, security: cleanPassword ? 'wpa2' : 'open' };
}

export async function writeWifiConfig(device, currentConfig, nextFields){
  const next = { ...(currentConfig || {}), ...validateWifiConfig(nextFields) };
  const data = JSON.stringify(next, null, 2);
  const code = `
try:
    import uos as os
except ImportError:
    import os
import json
payload = ${pyString(data)}
json.loads(payload)
with open('config.tmp', 'w') as f:
    f.write(payload)
with open('config.tmp', 'r') as f:
    json.loads(f.read())
try:
    os.remove('config.json.bak')
except OSError:
    pass
try:
    os.rename('config.json', 'config.json.bak')
except OSError:
    pass
os.rename('config.tmp', 'config.json')
print('config-ok')
`;
  const { stdout } = await device.exec(code, { timeoutMs: 10000 });
  if(!stdout.includes('config-ok')) throw new Error('device did not confirm config write');
  return next;
}

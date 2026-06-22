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

export function validateWifiConfig({ ssid }){
  return { ssid: validateSsid(ssid), password: '' };
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

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

export async function writeWifiConfig(device, currentConfig, nextFields, currentDeviceIdentity = null){
  const validated = validateWifiConfig(nextFields);
  const legacyConfig = { ...(currentConfig || {}), ...validated };
  const identityConfig = currentDeviceIdentity
    ? { ...currentDeviceIdentity, ap_ssid: validated.ssid, ap_password: validated.password, wifi_security: validated.security }
    : null;
  const legacyData = JSON.stringify(legacyConfig, null, 2);
  const identityData = identityConfig ? JSON.stringify(identityConfig, null, 2) : '';
  const code = `
try:
    import uos as os
except ImportError:
    import os
import json
legacy_payload = ${pyString(legacyData)}
identity_payload = ${pyString(identityData)}
def atomic_write(path, bak, payload):
    tmp = path + '.tmp'
    json.loads(payload)
    parent = path.rsplit('/', 1)[0] if '/' in path else ''
    if parent:
        try:
            os.mkdir(parent)
        except OSError:
            pass
    with open(tmp, 'w') as f:
        f.write(payload)
    with open(tmp, 'r') as f:
        json.loads(f.read())
    try:
        os.remove(bak)
    except OSError:
        pass
    try:
        os.rename(path, bak)
    except OSError:
        pass
    os.rename(tmp, path)
atomic_write('config.json', 'config.json.bak', legacy_payload)
if identity_payload:
    atomic_write('data/device.json', 'data/device.bak', identity_payload)
print('config-ok')
`;
  const { stdout } = await device.exec(code, { timeoutMs: 12000 });
  if(!stdout.includes('config-ok')) throw new Error('device did not confirm config write');
  return { config: legacyConfig, deviceIdentity: identityConfig };
}

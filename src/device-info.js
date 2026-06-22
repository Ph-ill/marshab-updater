function jsonReadSnippet(path){
  return `
import json
try:
    with open(${JSON.stringify(path)}, 'r') as f:
        print(f.read())
except OSError:
    print('null')
`;
}

function configVersionSnippet(){
  return `
import json
try:
    import config
    print(json.dumps({
        'project': 'MarsHab',
        'version': getattr(config, 'FIRMWARE_VERSION', 'unknown'),
        'runtime': 'micropython'
    }))
except Exception:
    print('null')
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

async function readConfigVersion(device){
  const { stdout } = await device.exec(configVersionSnippet(), { timeoutMs: 8000 });
  const text = stdout.trim();
  if(!text || text === 'null') return null;
  return JSON.parse(text);
}

export async function readDeviceInfo(device){
  const version = await readJsonFile(device, 'version.json') || await readConfigVersion(device);
  const config = await readJsonFile(device, 'config.json');
  const deviceIdentity = await readJsonFile(device, 'data/device.json');
  return { version, config, deviceIdentity };
}

export function summarizeDeviceInfo(info){
  const version = info.version?.version || 'unknown';
  const project = info.version?.project || 'unknown';
  const runtime = info.version?.runtime || 'micropython';
  const hab = info.deviceIdentity?.ap_ssid || info.deviceIdentity?.hab_name || info.config?.ssid || info.config?.habId || 'unknown';
  return { version, project, runtime, hab };
}

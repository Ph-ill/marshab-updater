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

export async function readDeviceInfo(device){
  const version = await readJsonFile(device, 'version.json');
  const config = await readJsonFile(device, 'config.json');
  return { version, config };
}

export function summarizeDeviceInfo(info){
  const version = info.version?.version || 'unknown';
  const project = info.version?.project || 'unknown';
  const runtime = info.version?.runtime || 'micropython';
  const hab = info.config?.ssid || info.config?.habId || 'unknown';
  return { version, project, runtime, hab };
}

const TEXT_CHUNK = 700;
const BINARY_CHUNK = 384;

function pyString(value){
  return JSON.stringify(value);
}

function splitString(text, size){
  const out = [];
  for(let i = 0; i < text.length; i += size) out.push(text.slice(i, i + size));
  return out;
}

function splitBytes(bytes, size){
  const out = [];
  for(let i = 0; i < bytes.length; i += size) out.push(bytes.slice(i, i + size));
  return out;
}

function bytesToBase64(bytes){
  let binary = '';
  for(let i = 0; i < bytes.length; i += 0x8000){
    binary += String.fromCharCode(...bytes.slice(i, i + 0x8000));
  }
  return btoa(binary);
}

export function parentDirs(path){
  const parts = path.split('/').filter(Boolean);
  const dirs = [];
  for(let i = 1; i < parts.length; i++) dirs.push(parts.slice(0, i).join('/'));
  return dirs;
}

export async function ensureDirs(device, dirs){
  const unique = [...new Set(dirs.filter(Boolean))];
  if(!unique.length) return;
  const code = `
try:
    import uos as os
except ImportError:
    import os
for d in ${JSON.stringify(unique)}:
    acc = ''
    for part in d.split('/'):
        acc = part if not acc else acc + '/' + part
        try:
            os.mkdir(acc)
        except OSError:
            pass
`;
  await device.exec(code, { timeoutMs: 10000 });
}

export async function removePaths(device, paths, preserve = []){
  const keep = new Set(preserve);
  const targets = paths.filter(path => path && !keep.has(path));
  if(!targets.length) return;
  const code = `
try:
    import uos as os
except ImportError:
    import os
for p in ${JSON.stringify(targets)}:
    try:
        os.remove(p)
    except OSError:
        pass
`;
  await device.exec(code, { timeoutMs: 10000 });
}

export async function writeUtf8File(device, path, text, { onProgress = null } = {}){
  await ensureDirs(device, parentDirs(path));
  await device.exec(`open(${pyString(path)}, 'w').close()`, { timeoutMs: 10000 });
  const chunks = splitString(text, TEXT_CHUNK);
  for(let i = 0; i < chunks.length; i++){
    const code = `
with open(${pyString(path)}, 'a') as f:
    f.write(${pyString(chunks[i])})
`;
    await device.exec(code, { timeoutMs: 10000 });
    if(onProgress) onProgress({ path, done: i + 1, total: chunks.length });
  }
}

export async function writeBinaryFile(device, path, bytes, { onProgress = null } = {}){
  await ensureDirs(device, parentDirs(path));
  await device.exec(`open(${pyString(path)}, 'wb').close()`, { timeoutMs: 10000 });
  const chunks = splitBytes(bytes, BINARY_CHUNK);
  for(let i = 0; i < chunks.length; i++){
    const b64 = bytesToBase64(chunks[i]);
    const code = `
try:
    import ubinascii as binascii
except ImportError:
    import binascii
with open(${pyString(path)}, 'ab') as f:
    f.write(binascii.a2b_base64(${pyString(b64)}))
`;
    await device.exec(code, { timeoutMs: 15000 });
    if(onProgress) onProgress({ path, done: i + 1, total: chunks.length });
  }
}

export async function statSize(device, path){
  const code = `
try:
    import uos as os
except ImportError:
    import os
try:
    print(os.stat(${pyString(path)})[6])
except OSError:
    print(-1)
`;
  const { stdout } = await device.exec(code, { timeoutMs: 8000 });
  return Number(stdout.trim());
}

export async function verifySize(device, path, expectedSize){
  const actual = await statSize(device, path);
  if(actual !== expectedSize) throw new Error(`${path} size mismatch: expected ${expectedSize}, got ${actual}`);
  return true;
}

export async function writeManifestFile(device, file, bytes, { onProgress = null } = {}){
  if(file.encoding === 'utf8'){
    const text = new TextDecoder().decode(bytes);
    await writeUtf8File(device, file.path, text, { onProgress });
  }else{
    await writeBinaryFile(device, file.path, bytes, { onProgress });
  }
  await verifySize(device, file.path, file.size);
}

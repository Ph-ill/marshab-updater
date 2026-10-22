// Copy log files off the board over the same raw-REPL link (base64 chunks, so binary-safe).
const READ_CHUNK = 2048;

export async function statFiles(device, paths){
  const code = `
import os, json
out = {}
for p in ${JSON.stringify(paths)}:
    try:
        out[p] = os.stat(p)[6]
    except OSError:
        out[p] = -1
print(json.dumps(out))
`;
  const { stdout } = await device.exec(code, { timeoutMs: 8000 });
  return JSON.parse(stdout.trim());
}

export async function readFileBytes(device, path, size, { onProgress = null } = {}){
  const parts = [];
  let offset = 0;
  while(offset < size){
    const code = `
import binascii
with open(${JSON.stringify(path)}, 'rb') as f:
    f.seek(${offset})
    b = f.read(${READ_CHUNK})
print(binascii.b2a_base64(b).decode().strip())
`;
    const { stdout } = await device.exec(code, { timeoutMs: 10000 });
    const bin = atob(stdout.trim());
    if(!bin.length) break; // file shrank (rotation) while reading
    const bytes = new Uint8Array(bin.length);
    for(let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    parts.push(bytes);
    offset += bytes.length;
    if(onProgress) onProgress({ path, done: offset, total: size });
  }
  const out = new Uint8Array(offset);
  let at = 0;
  for(const p of parts){ out.set(p, at); at += p.length; }
  return out;
}

export function logFileName(path, ship, when = new Date()){
  const base = path.split('/').pop();
  const dot = base.lastIndexOf('.');
  const stem = dot > 0 ? base.slice(0, dot) : base;
  const ext = dot > 0 ? base.slice(dot) : '';
  const who = ship ? `_${ship.role ? ship.role : ''}${ship.ship_id ? `ship${ship.ship_id}` : ''}` : '';
  const stamp = when.toISOString().slice(0, 16).replace(/[-:]/g, '').replace('T', '-');
  return `${stem}${who}_${stamp}${ext}`;
}

export function saveBytes(bytes, filename, type = 'text/csv'){
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

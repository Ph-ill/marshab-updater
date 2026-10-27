import { fetchJson } from './releases.js';
import { runtimeSnippet } from './device-info.js';
import { removePaths, snapshotProtectedData, verifyProtectedData, wipeExcept, writeManifestFile } from './file-transfer.js';

export async function fetchBytes(url){
  const response = await fetch(url, { cache:'no-store' });
  if(!response.ok) throw new Error(`${url} returned ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

export function decodeBase64Bytes(data){
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for(let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function findRelease(indexManifest, version){
  return (indexManifest.releases || []).find(release => release.version === version) || null;
}

export async function loadReleaseManifest(indexManifest, version){
  const release = findRelease(indexManifest, version);
  if(!release) throw new Error(`release ${version} not found`);
  return fetchJson(release.path); // a static file in this repo: /firmware/releases/<version>/release.json
}

function orderedFiles(files){
  const copy = [...files];
  copy.sort((a, b) => {
    if(a.path === 'version.json') return 1;
    if(b.path === 'version.json') return -1;
    return a.path.localeCompare(b.path);
  });
  return copy;
}

async function sha256Hex(bytes){
  // Web Serial itself needs a secure context (https / localhost), so SubtleCrypto is always there when it matters.
  if(!globalThis.crypto?.subtle) throw new Error('this page needs https (or localhost) to check file hashes');
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// Check every file before touching the board, so a bad download never half-installs.
export async function prepareFiles(releaseManifest){
  const out = [];
  for(const file of orderedFiles(releaseManifest.files || [])){
    if(typeof file.path !== 'string' || !file.path || file.path.startsWith('/') || file.path.split('/').includes('..')){
      throw new Error(`release lists an unsafe path: ${file.path}`);
    }
    const bytes = file.data ? decodeBase64Bytes(file.data) : await fetchBytes(file.url);
    if(bytes.length !== file.size) throw new Error(`${file.path} download size mismatch`);
    if(!file.sha256) throw new Error(`${file.path} has no sha256 in the release`);
    if(await sha256Hex(bytes) !== file.sha256) throw new Error(`${file.path} sha256 mismatch in download`);
    out.push({ file, bytes });
  }
  return out;
}

// A partial release (release.frozen) carries only what changed on top of one exact frozen game
// core: it is refused on stock MicroPython or another core, before anything is written.
export function frozenMismatch(releaseManifest, runtime){
  const need = releaseManifest?.frozen;
  if(!need) return null;
  const want = `${need.id} ${need.version} (core ${need.requires})`;
  const uf2 = `lv-core-${need.version}-${need.requires}-<board>.uf2`;
  const have = runtime?.frozen;
  if(!runtime) return `${releaseManifest.version} needs the game firmware ${want}, and this board's firmware could not be read`;
  if(!have) return `${releaseManifest.version} needs the game firmware ${want}; this board runs stock MicroPython. Flash ${uf2} first (BOOTSEL, see game/docs/BENCH_TEST.md)`;
  if(have.id !== need.id || have.core !== need.requires) return `${releaseManifest.version} needs the game firmware ${want}; this board has ${have.id} ${have.version} (core ${have.core}). Flash ${uf2} first`;
  return null;
}

// lv-core 0.2.0+ froze the board modules and the story pack too (release.frozen.board,
// .pack). On the board a file is found before a frozen module, so every copy the release
// doesn't ship (<module>.py, <module>.mpy, pack.bin, e.g. left by a 0.1.0 install) has to
// go, or it would run instead of the firmware's. tools/build_release.py lists these in
// "delete" as well; this keeps older or hand-made releases safe too.
export function frozenStale(releaseManifest){
  const fz = releaseManifest?.frozen;
  if(!fz) return [];
  const ship = new Set((releaseManifest.files || []).map(f => f.path));
  const out = [];
  for(const m of fz.board || []) for(const ext of ['.py', '.mpy']) if(!ship.has(m + ext)) out.push(m + ext);
  if(fz.pack && !ship.has('pack.bin')) out.push('pack.bin');
  return out;
}

export async function readRuntime(device){
  const { stdout } = await device.exec(runtimeSnippet(), { timeoutMs: 8000 });
  return JSON.parse(stdout.trim());
}

export async function installRelease(device, releaseManifest, { clean = false, onLog = () => {}, onProgress = () => {}, onBeforeReset = () => {} } = {}){
  const preserve = [...new Set([...(releaseManifest.preserve || []), 'data/'])];
  onLog(`installing ${releaseManifest.project || 'firmware'} ${releaseManifest.version}`);
  if(releaseManifest.frozen){
    let runtime = null;
    try{ runtime = await readRuntime(device); }catch(_err){ runtime = null; }
    const why = frozenMismatch(releaseManifest, runtime);
    if(why) throw new Error(why);
    onLog(`game firmware ${releaseManifest.frozen.id} core ${releaseManifest.frozen.requires} matches; overrides: [${(releaseManifest.overrides || []).join(', ')}]`);
  }
  onLog('checking release files');
  const prepared = await prepareFiles(releaseManifest);
  onLog('snapshotting protected device data');
  await snapshotProtectedData(device);
  if(clean){
    onLog(`clean install: removing old files (keeping ${preserve.join(', ')})`);
    onLog(await wipeExcept(device, preserve));
  }
  // ota/: an over-the-air update staged or on trial on the board (game/board/lvota.py). Left
  // there, the board's boot.py would swap it in over this install, or "roll back" to it.
  const gone = [...new Set([...(releaseManifest.delete || []), ...frozenStale(releaseManifest), 'ota'])];
  if(gone.length){
    onLog(`removing ${gone.length} obsolete path(s)`);
    await removePaths(device, gone, preserve);
  }

  for(let i = 0; i < prepared.length; i++){
    const { file, bytes } = prepared[i];
    onLog(`writing ${file.path} (${i + 1}/${prepared.length})`);
    await writeManifestFile(device, file, bytes, {
      preserve,
      onProgress: progress => onProgress({ file, fileIndex: i + 1, fileTotal: prepared.length, ...progress }),
    });
  }

  onLog('verifying protected device data');
  await verifyProtectedData(device);
  onLog('shutting down AP and hard-resetting device');
  onBeforeReset();
  await device.firmwareInstallReset();
  return true;
}

import { fetchJson } from './releases.js';
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

export async function installRelease(device, releaseManifest, { clean = false, onLog = () => {}, onProgress = () => {}, onBeforeReset = () => {} } = {}){
  const preserve = [...new Set([...(releaseManifest.preserve || []), 'data/'])];
  onLog(`installing ${releaseManifest.project || 'firmware'} ${releaseManifest.version}`);
  onLog('checking release files');
  const prepared = await prepareFiles(releaseManifest);
  onLog('snapshotting protected device data');
  await snapshotProtectedData(device);
  if(clean){
    onLog(`clean install: removing old files (keeping ${preserve.join(', ')})`);
    onLog(await wipeExcept(device, preserve));
  }
  if(releaseManifest.delete?.length){
    onLog(`removing ${releaseManifest.delete.length} obsolete path(s)`);
    await removePaths(device, releaseManifest.delete, preserve);
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

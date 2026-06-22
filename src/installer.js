import { removePaths, writeManifestFile } from './file-transfer.js';

export async function fetchJson(url){
  const isGithubAsset = (url.startsWith('https://api.github.com/repos/') || url.startsWith('/github-api/repos/')) && url.includes('/releases/assets/');
  const response = await fetch(url, {
    cache:'no-store',
    headers: isGithubAsset ? { Accept:'application/octet-stream' } : {},
  });
  if(!response.ok) throw new Error(`${url} returned ${response.status}`);
  try{
    return await response.json();
  }catch(err){
    throw new Error(`could not read firmware release JSON from ${url}: ${err.message}`);
  }
}

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
  return fetchJson(release.path);
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

export async function installRelease(device, releaseManifest, { onLog = () => {}, onProgress = () => {} } = {}){
  const preserve = releaseManifest.preserve || [];
  onLog(`installing ${releaseManifest.project || 'firmware'} ${releaseManifest.version}`);
  if(releaseManifest.delete?.length){
    onLog(`removing ${releaseManifest.delete.length} obsolete path(s)`);
    await removePaths(device, releaseManifest.delete, preserve);
  }

  const files = orderedFiles(releaseManifest.files || []);
  for(let i = 0; i < files.length; i++){
    const file = files[i];
    onLog(`writing ${file.path} (${i + 1}/${files.length})`);
    const bytes = file.data ? decodeBase64Bytes(file.data) : await fetchBytes(file.url);
    if(bytes.length !== file.size) throw new Error(`${file.path} download size mismatch`);
    await writeManifestFile(device, file, bytes, {
      onProgress: progress => onProgress({ file, fileIndex: i + 1, fileTotal: files.length, ...progress }),
    });
  }

  onLog('soft-resetting device');
  await device.softReset();
  return true;
}

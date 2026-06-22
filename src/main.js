import { MicroPythonSerial } from './webserial-micropython.js';
import { readDeviceInfo, summarizeDeviceInfo } from './device-info.js';
import { installRelease, loadReleaseManifest } from './installer.js';
import { loadGithubReleaseIndex } from './github-releases.js';

const state = {
  manifest: null,
  selectedVersion: null,
  device: null,
  deviceInfo: null,
};

const els = {
  supportNotice: document.getElementById('supportNotice'),
  deviceStatus: document.getElementById('deviceStatus'),
  deviceProject: document.getElementById('deviceProject'),
  deviceHab: document.getElementById('deviceHab'),
  installedVersion: document.getElementById('installedVersion'),
  latestVersion: document.getElementById('latestVersion'),
  latestStable: document.getElementById('latestStable'),
  releaseSelect: document.getElementById('releaseSelect'),
  connectBtn: document.getElementById('connectBtn'),
  installLatestBtn: document.getElementById('installLatestBtn'),
  installSelectedBtn: document.getElementById('installSelectedBtn'),
  progressTrack: document.querySelector('.progress-track'),
  progressFill: document.getElementById('progressFill'),
  progressPercent: document.getElementById('progressPercent'),
  progressStatus: document.getElementById('progressStatus'),
  log: document.getElementById('log'),
};

function stamp(){ return new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit', second:'2-digit' }); }
function log(message){
  const li = document.createElement('li');
  const time = document.createElement('time');
  const span = document.createElement('span');
  time.textContent = stamp();
  span.textContent = message;
  li.append(time, span);
  els.log.append(li);
  els.log.scrollTop = els.log.scrollHeight;
}
function setText(el, value){ el.textContent = value == null || value === '' ? '—' : String(value); }
function setStatus(text, className){ els.deviceStatus.textContent = text; els.deviceStatus.className = className || ''; }
function supportsWebSerial(){ return 'serial' in navigator; }
function setProgress(percent, status, mode = ''){
  const value = Math.max(0, Math.min(100, Math.round(percent || 0)));
  els.progressFill.style.width = `${value}%`;
  els.progressPercent.textContent = `${value}%`;
  els.progressTrack.setAttribute('aria-valuenow', String(value));
  els.progressTrack.classList.toggle('complete', mode === 'complete');
  els.progressTrack.classList.toggle('failed', mode === 'failed');
  if(status) els.progressStatus.textContent = status;
}
function resetProgress(status = 'Standing by. Connect a device and select a release.'){
  setProgress(0, status, '');
}

async function loadManifest(){
  try{
    return await loadGithubReleaseIndex();
  }catch(err){
    log(`GitHub release index unavailable, trying bundled fallback: ${err.message}`);
    const response = await fetch('./firmware/manifest.json', { cache:'no-store' });
    if(!response.ok) throw new Error(`manifest ${response.status}`);
    return response.json();
  }
}
function releaseLabel(release){
  const parts = [release.version];
  if(release.label) parts.push(release.label);
  if(release.date) parts.push(`(${release.date})`);
  return parts.join(' ');
}
function setBusy(busy){
  els.connectBtn.disabled = busy;
  els.releaseSelect.disabled = busy;
  const hasRelease = !!(state.manifest?.releases?.length);
  els.installLatestBtn.disabled = busy || !hasRelease || !state.device;
  els.installSelectedBtn.disabled = busy || !hasRelease || !state.device;
}
function renderManifest(manifest){
  state.manifest = manifest;
  const latest = manifest.latest || 'none';
  setText(els.latestVersion, latest);
  setText(els.latestStable, latest);
  els.releaseSelect.innerHTML = '';
  for(const release of manifest.releases || []){
    const option = document.createElement('option');
    option.value = release.version;
    option.textContent = releaseLabel(release);
    els.releaseSelect.append(option);
  }
  if(manifest.latest) els.releaseSelect.value = manifest.latest;
  state.selectedVersion = els.releaseSelect.value || null;
  setBusy(false);
  const hasRelease = !!(manifest.releases && manifest.releases.length);
  log(hasRelease ? `release index loaded: latest ${latest}` : 'release index loaded: no releases published');
}
function renderDeviceInfo(info){
  const summary = summarizeDeviceInfo(info);
  setText(els.installedVersion, summary.version);
  setText(els.deviceProject, summary.project);
  setText(els.deviceHab, summary.hab);
  if(state.manifest?.latest && summary.version === state.manifest.latest) log(`device is current: ${summary.version}`);
  else if(summary.version === 'unknown') log('device version is unknown; install latest when ready');
  else if(state.manifest?.latest) log(`update available: installed ${summary.version}, latest ${state.manifest.latest}`);
}
function clearDeviceUi(){
  setText(els.installedVersion, '—');
  setText(els.deviceProject, '—');
  setText(els.deviceHab, '—');
}
function initBrowserSupport(){
  if(!supportsWebSerial()){
    els.supportNotice.hidden = false;
    els.connectBtn.disabled = true;
    setStatus('unsupported browser', 'status-bad');
    log('WebSerial unavailable; use desktop Chrome, Edge, Brave, or Chromium');
    return;
  }
  setStatus('disconnected', 'status-warn');
  log('WebSerial available; waiting for Pico W');
}
async function connectDevice(){
  if(state.device){
    await state.device.disconnect();
    state.device = null;
    state.deviceInfo = null;
    setStatus('disconnected', 'status-warn');
    clearDeviceUi();
    resetProgress();
    els.connectBtn.textContent = 'Connect device';
    setBusy(false);
    log('device disconnected');
    return;
  }
  els.connectBtn.disabled = true;
  setStatus('connecting', 'status-warn');
  try{
    const device = new MicroPythonSerial();
    log('opening browser serial chooser');
    await device.connect();
    log('serial port open; entering MicroPython raw REPL');
    await device.enterRawRepl();
    const probe = await device.exec("print('ok')");
    if(!probe.stdout.includes('ok')) throw new Error('MicroPython probe did not return ok');
    log('MicroPython probe ok');
    state.device = device;
    els.connectBtn.textContent = 'Disconnect device';
    setStatus('connected', 'status-ok');
    log('reading device version/config');
    state.deviceInfo = await readDeviceInfo(device);
    renderDeviceInfo(state.deviceInfo);
    setBusy(false);
  }catch(err){
    if(state.device){ try{ await state.device.disconnect(); }catch(_err){} }
    state.device = null;
    setStatus('connection failed', 'status-bad');
    log(`connection failed: ${err.message}`);
  }finally{
    els.connectBtn.disabled = false;
  }
}
async function refreshDeviceInfoAfterInstall(){
  log('waiting for device reset');
  await new Promise(resolve => setTimeout(resolve, 1800));
  try{
    await state.device.enterRawRepl();
    state.deviceInfo = await readDeviceInfo(state.device);
    renderDeviceInfo(state.deviceInfo);
    setStatus('connected', 'status-ok');
    log('device version check complete');
  }catch(err){
    setStatus('reconnect needed', 'status-warn');
    log(`reset complete; click Disconnect then Connect if version did not refresh (${err.message})`);
  }
}
async function installVersion(version){
  if(!version){ log('no release selected'); return; }
  if(!state.device){ log('connect a device first'); return; }
  setBusy(true);
  setStatus('installing', 'status-warn');
  resetProgress(`Preparing ${version} install.`);
  try{
    const release = await loadReleaseManifest(state.manifest, version);
    if(version !== state.manifest.latest){
      const ok = confirm(`Install ${version}? This replaces firmware files but preserves config/save/ledger.`);
      if(!ok){ log('install cancelled'); return; }
    }
    await installRelease(state.device, release, {
      onLog: log,
      onProgress: ({ file, fileIndex, fileTotal, done, total }) => {
        const percent = ((fileIndex - 1) + (done / Math.max(1, total))) / Math.max(1, fileTotal) * 100;
        setProgress(percent, `Writing ${file.path} · chunk ${done}/${total}`);
        if(done === total) log(`verified ${file.path}`);
      },
    });
    setProgress(100, `Install ${release.version} complete. Resetting device.`, 'complete');
    await refreshDeviceInfoAfterInstall();
  }catch(err){
    setStatus('install failed', 'status-bad');
    setProgress(100, `Install failed: ${err.message}`, 'failed');
    log(`install failed: ${err.message}`);
  }finally{
    setBusy(false);
  }
}
function initEvents(){
  els.releaseSelect.addEventListener('change', () => {
    state.selectedVersion = els.releaseSelect.value || null;
    log(`selected release ${state.selectedVersion || 'none'}`);
  });
  els.connectBtn.addEventListener('click', () => { connectDevice(); });
  els.installLatestBtn.addEventListener('click', () => { installVersion(state.manifest?.latest); });
  els.installSelectedBtn.addEventListener('click', () => { installVersion(state.selectedVersion); });
}
async function main(){
  initBrowserSupport();
  initEvents();
  try{ renderManifest(await loadManifest()); }
  catch(err){
    setText(els.latestVersion, 'manifest error');
    setText(els.latestStable, 'manifest error');
    els.latestVersion.className = 'status-bad';
    log(`failed to load firmware manifest: ${err.message}`);
  }
}
main();

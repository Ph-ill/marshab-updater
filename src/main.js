import { MicroPythonSerial } from './webserial-micropython.js';
import { readDeviceInfo, summarizeDeviceInfo } from './device-info.js';
import { installRelease, loadReleaseManifest } from './installer.js';
import { loadReleaseIndex, compareVersions } from './releases.js';
import { loadRuntimeSpec } from './releases.js';
import { runtimeStatus, boardSupported, rebootToBootsel, verifyCommands } from './runtime.js';
import { validateShipConfig, writeShipConfig, defaultShipName, hotspotSummary, hotspotForRole } from './ship-config.js';
import { loadRoleHistory, recordRole, suggestRole, roleClash, lastOtherBoard, describeBoard } from './role-memory.js';
import { statFiles, readFileBytes, logFileName, saveBytes } from './device-logs.js';

const SHIP_COUNT = 7;
const DEFAULT_LOGS = ['coex_log.csv', 'coex_log.old', 'coex_boot.txt'];

const state = {
  index: null,
  selectedVersion: null,
  releaseCache: new Map(),
  runtime: null,
  device: null,
  deviceInfo: null,
  resetInProgress: false,
  busy: false,
  logSizes: {},
  shipFormFor: null,   // board the ship form was last filled for (its defaults are applied once per connection)
};

const $ = id => document.getElementById(id);
const els = {
  supportNotice: $('supportNotice'),
  deviceStatus: $('deviceStatus'),
  deviceBoard: $('deviceBoard'),
  deviceRuntime: $('deviceRuntime'),
  deviceShip: $('deviceShip'),
  deviceFs: $('deviceFs'),
  installedVersion: $('installedVersion'),
  latestVersion: $('latestVersion'),
  releaseSelect: $('releaseSelect'),
  releaseNeeds: $('releaseNeeds'),
  releaseNotes: $('releaseNotes'),
  cleanInstall: $('cleanInstall'),
  connectBtn: $('connectBtn'),
  installLatestBtn: $('installLatestBtn'),
  installSelectedBtn: $('installSelectedBtn'),
  progressPanel: $('progressPanel'),
  progressTrack: document.querySelector('.progress-track'),
  progressFill: $('progressFill'),
  progressPercent: $('progressPercent'),
  progressStatus: $('progressStatus'),
  log: $('log'),
  powerCycleModal: $('powerCycleModal'),
  powerCycleDoneBtn: $('powerCycleDoneBtn'),
  powerCycleSsid: $('powerCycleSsid'),
};
Object.assign(els, {
  runtimeState: $('runtimeState'),
  bootselBtn: $('bootselBtn'),
  uf2List: $('uf2List'),
  driveNames: $('driveNames'),
});
Object.assign(els, {
  shipId: $('shipId'),
  shipName: $('shipName'),
  shipRole: $('shipRole'),
  shipSsid: $('shipSsid'),
  shipRoleWarn: $('shipRoleWarn'),
  shipPassword: $('shipPassword'),
  shipOpen: $('shipOpen'),
  shipShowPw: $('shipShowPw'),
  shipHotspot: $('shipHotspot'),
  saveShipBtn: $('saveShipBtn'),
});
Object.assign(els, {
  logList: $('logList'),
  refreshLogsBtn: $('refreshLogsBtn'),
  downloadAllLogsBtn: $('downloadAllLogsBtn'),
});

// ---------------------------------------------------------------- small helpers
function stamp(){ return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }); }
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
function resetProgress(status = 'Standing by.', visible = false){
  els.progressPanel.hidden = !visible;
  setProgress(0, status, '');
}
function hotspotName(){
  const role = state.deviceInfo?.ship?.role;
  return role ? hotspotForRole(role) : 'the ship hotspot (COEX-0 or COEX-1)';
}
function showPowerCycleModal(){
  els.powerCycleSsid.textContent = hotspotName();
  els.powerCycleModal.hidden = false;
  els.powerCycleDoneBtn.focus();
}
function hidePowerCycleModal(){ els.powerCycleModal.hidden = true; }

function releaseLabel(release){
  const parts = [release.version];
  if(release.label && release.label !== release.version) parts.push(`· ${release.label}`);
  if(release.channel && release.channel !== 'stable') parts.push(`[${release.channel}]`);
  if(release.date) parts.push(`(${release.date})`);
  return parts.join(' ');
}

// "RPI_PICO2_W" -> "Pico 2 W" (from runtime.json when it is loaded)
function boardLabel(id){
  return state.runtime?.boards?.[id]?.label?.replace(/^Raspberry Pi /, '') || id.replace(/^RPI_/, '').replace(/_/g, ' ');
}

function deviceControls(){
  const list = [];
  list.push(els.shipId, els.shipName, els.shipRole, els.shipPassword, els.shipOpen, els.saveShipBtn);
  list.push(els.refreshLogsBtn, els.downloadAllLogsBtn, ...els.logList.querySelectorAll('button'));
  list.push(els.bootselBtn);
  return list;
}

function setBusy(busy){
  state.busy = busy;
  const dev = !!state.device;
  const hasRelease = !!(state.index?.releases?.length);
  els.connectBtn.disabled = busy || !supportsWebSerial();
  els.releaseSelect.disabled = busy || !hasRelease;
  els.installLatestBtn.disabled = busy || !hasRelease || !dev;
  els.installSelectedBtn.disabled = busy || !hasRelease || !dev;
  els.cleanInstall.disabled = busy;
  for(const el of deviceControls()) el.disabled = busy || !dev;
  if(!busy && dev) els.shipPassword.disabled = els.shipOpen.checked;
}

// ---------------------------------------------------------------- releases
async function getRelease(version){
  if(state.releaseCache.has(version)) return state.releaseCache.get(version);
  const release = await loadReleaseManifest(state.index, version);
  state.releaseCache.set(version, release);
  return release;
}

async function describeSelected(){
  const version = state.selectedVersion;
  els.releaseNotes.hidden = true;
  setText(els.releaseNeeds, '—');
  if(!version) return;
  try{
    const release = await getRelease(version);
    if(version !== state.selectedVersion) return;
    const needs = [];
    if(release.runtime?.min) needs.push(`MicroPython ${release.runtime.min}+`);
    if(release.boards?.length) needs.push(release.boards.map(boardLabel).join(' / '));
    const bytes = release.payload_bytes || (release.files || []).reduce((n, f) => n + (f.size || 0), 0);
    needs.push(`${(release.files || []).length} files, ${Math.round(bytes / 1024)} KB`);
    setText(els.releaseNeeds, needs.join(' · '));
    if(release.notes){ els.releaseNotes.textContent = release.notes; els.releaseNotes.hidden = false; }
    renderRuntimePanel();
    renderShipFields();
  }catch(err){
    setText(els.releaseNeeds, 'could not load release');
    log(`release ${version}: ${err.message}`);
  }
}

function renderIndex(index){
  state.index = index;
  state.releaseCache.clear();
  setText(els.latestVersion, index.latest || 'none published');
  els.releaseSelect.innerHTML = '';
  for(const release of index.releases || []){
    const option = document.createElement('option');
    option.value = release.version;
    option.textContent = releaseLabel(release);
    els.releaseSelect.append(option);
  }
  if(index.latest) els.releaseSelect.value = index.latest;
  state.selectedVersion = els.releaseSelect.value || null;
  setBusy(false);
  log(index.releases?.length ? `release list loaded: latest ${index.latest}` : 'no releases published yet');
  describeSelected();
  if(state.deviceInfo) reportVersion(state.deviceInfo);
}

// ---------------------------------------------------------------- device info
function reportVersion(info){
  const latest = state.index?.latest;
  const installed = info.version?.project === 'LongVoyage' ? info.version.version : null;
  if(!latest) return;
  if(!installed) log(`no Long Voyage release on this board yet; install ${latest} when ready`);
  else if(compareVersions(installed, latest) === 0) log(`ship software is current: ${installed}`);
  else if(compareVersions(installed, latest) < 0) log(`update available: installed ${installed}, latest ${latest}`);
  else log(`installed ${installed} is newer than latest ${latest}`);
}

function renderDeviceInfo(info, { quiet = false } = {}){
  const summary = summarizeDeviceInfo(info);
  setText(els.installedVersion, summary.version);
  setText(els.deviceShip, summary.name);
  setText(els.deviceBoard, summary.board);
  setText(els.deviceRuntime, summary.runtime);
  setText(els.deviceFs, summary.fs);
  if(summary.kind === 'other' && !quiet) log('this board holds files from another project; the install will offer to clear them');
  renderShipFields();
  renderRuntimePanel();
  if(!quiet) reportVersion(info);
}

function clearDeviceUi(){
  for(const el of [els.installedVersion, els.deviceShip, els.deviceBoard, els.deviceRuntime, els.deviceFs]) setText(el, '—');
  state.shipFormFor = null;
  els.shipName.value = '';
  els.shipPassword.value = '';
  els.shipOpen.checked = false;
  els.shipRole.value = '';
  setText(els.shipHotspot, '—');
  renderShipSsid();
  els.logList.innerHTML = '<li class="muted">Connect a ship to list its log files.</li>';
  renderRuntimePanel();
}

function markDeviceDisconnected(reason = 'ship disconnected'){
  if(state.resetInProgress){
    log(`${reason}; waiting for the ship to come back`);
    return;
  }
  if(!state.device && els.connectBtn.textContent === 'Connect ship') return;
  state.device = null;
  state.deviceInfo = null;
  setStatus('disconnected', 'status-warn');
  clearDeviceUi();
  resetProgress();
  els.connectBtn.textContent = 'Connect ship';
  setBusy(false);
  log(reason);
}

// Enter the raw REPL and make it safe to work in: stop a running watchdog, mute BLE callbacks.
async function openRepl(device){
  await device.enterRawRepl();
  const probe = await device.exec("print('ok')", { timeoutMs: 5000 });
  if(!probe.stdout.includes('ok')) throw new Error('MicroPython probe did not return ok');
  let wdt = await device.quiesce();
  if(wdt === 'stopped') log('watchdog was running; paused it for this session');
  if(wdt === 'still-on'){
    log('watchdog could not be paused; restarting the board in maintenance mode');
    wdt = await device.maintenanceReboot();
    log(`after the maintenance restart the watchdog reads ${wdt}`);
  }
}

async function reconnectAfterReset(device, attempts = 12){
  await device.reopenExisting({ attempts, delayMs: 900 });
  await openRepl(device);
  state.device = device;
  state.deviceInfo = await readDeviceInfo(device);
  renderDeviceInfo(state.deviceInfo);
  setStatus('connected', 'status-ok');
  els.connectBtn.textContent = 'Disconnect ship';
}

async function connectDevice(){
  if(state.device){
    const device = state.device;
    setBusy(true);
    log('restarting the ship and closing the USB link');
    await device.disconnect({ reset: true });
    markDeviceDisconnected('ship disconnected; it restarted and is running its software again');
    return;
  }
  els.connectBtn.disabled = true;
  setStatus('connecting', 'status-warn');
  try{
    const device = new MicroPythonSerial({ onDisconnect: markDeviceDisconnected });
    log('opening the browser serial port chooser');
    await device.connect();
    log('serial port open; entering the MicroPython REPL (this pauses the ship software)');
    await openRepl(device);
    state.device = device;
    els.connectBtn.textContent = 'Disconnect ship';
    setStatus('connected', 'status-ok');
    log('reading board, runtime and ship settings');
    state.deviceInfo = await readDeviceInfo(device);
    renderDeviceInfo(state.deviceInfo);
    if(!state.deviceInfo.ship) log('this board has no ship settings yet; fill in section 4 and save');
    setBusy(false);
  }catch(err){
    if(state.device){ try{ await state.device.disconnect(); }catch(_err){} }
    state.device = null;
    setStatus('connection failed', 'status-bad');
    log(`connection failed: ${err.message}`);
    setBusy(false);
  }
}

// ---------------------------------------------------------------- ship config
function shipRoles(){
  const release = state.releaseCache.get(state.selectedVersion);
  return release?.shipConfig?.roles || [];
}

function renderShipFields(){
  if(els.shipId.options.length !== SHIP_COUNT){
    els.shipId.innerHTML = '';
    for(let i = 1; i <= SHIP_COUNT; i++){
      const o = document.createElement('option');
      o.value = String(i);
      o.textContent = String(i);
      els.shipId.append(o);
    }
  }
  const roles = shipRoles();
  const current = els.shipRole.value;
  els.shipRole.innerHTML = '<option value="">none</option>';
  for(const r of roles){
    const o = document.createElement('option');
    o.value = r;
    o.textContent = r;
    els.shipRole.append(o);
  }
  els.shipRole.value = roles.includes(current) ? current : '';
  const cfg = state.deviceInfo?.ship;
  if(cfg){
    els.shipId.value = String(cfg.ship_id || 1);
    els.shipName.value = cfg.ship_name || '';
    els.shipPassword.value = '';
    els.shipOpen.checked = !!cfg.hotspot_open;
    if(cfg.role && roles.includes(cfg.role)) els.shipRole.value = cfg.role;
  }
  const formKey = state.device ? (state.deviceInfo?.uid || 'board') : null;
  if(formKey && roles.length && state.deviceInfo && state.shipFormFor !== formKey){
    state.shipFormFor = formKey;
    applyShipDefaults(cfg, roles);
  }
  setText(els.shipHotspot, state.device ? hotspotSummary(cfg) : '—');
  renderShipSsid();
  els.shipName.placeholder = defaultShipName(els.shipId.value || 1);
  els.shipPassword.disabled = !state.device || state.busy || els.shipOpen.checked;
}

// First fill of the form for a newly connected board: if it has no role yet, preselect one the last
// board configured from this browser is not using.
function applyShipDefaults(cfg, roles){
  if(cfg?.role) return;
  const uid = state.deviceInfo?.uid || null;
  const history = loadRoleHistory();
  const suggestion = suggestRole(history, uid, roles);
  if(!suggestion) return;
  const last = lastOtherBoard(history, uid);
  els.shipRole.value = suggestion;
  log(`preselected role ${suggestion} (${hotspotForRole(suggestion, roles)}): the last board configured here, ${describeBoard(last)}, is role ${last.role || 'none'}`);
}

// The clash this board would have with the last other board configured from this browser, if any.
function currentClash(){
  if(!state.device) return null;
  return roleClash(loadRoleHistory(), state.deviceInfo?.uid || null, els.shipRole.value, shipRoles());
}

// Live "→ COEX-n" tag next to the role select: the network name this board will broadcast,
// turned rust with a warning underneath when the last other board broadcasts the same one.
function renderShipSsid(){
  const roles = shipRoles();
  const role = els.shipRole.value;
  const ssid = roles.length ? hotspotForRole(role, roles) : '—';
  els.shipSsid.textContent = ssid;
  els.shipSsid.title = role ? `Role ${role} broadcasts ${ssid}` : `No role: the firmware default, ${ssid} (same as role ${roles[0] || 'A'})`;
  const clash = roles.length ? currentClash() : null;
  els.shipSsid.classList.toggle('clash', !!clash);
  els.shipRoleWarn.hidden = !clash;
  if(clash){
    const other = roles.find(r => hotspotForRole(r, roles) !== ssid);
    els.shipRoleWarn.textContent = `Same hotspot as the last board configured here: ${describeBoard(clash)} is role ${clash.role || 'none'} → ${ssid}. `
      + `Two boards on one role ignore each other over BLE.${other ? ` Pick role ${other} for this one.` : ''}`;
  }
}

async function saveShipConfig(){
  if(!state.device){ log('connect a ship first'); return; }
  setBusy(true);
  try{
    const previous = state.deviceInfo?.ship || {};
    const typed = els.shipPassword.value;
    const cfg = validateShipConfig({
      ship_id: els.shipId.value,
      ship_name: els.shipName.value || defaultShipName(els.shipId.value),
      // blank keeps whatever password the ship already has (or the firmware's WPA2 default)
      hotspot_password: typed || (els.shipOpen.checked ? '' : previous.hotspot_password || ''),
      hotspot_open: els.shipOpen.checked,
      role: els.shipRole.value,
    }, { count: SHIP_COUNT, roles: shipRoles() });
    const clash = roleClash(loadRoleHistory(), state.deviceInfo?.uid || null, cfg.role, shipRoles());
    if(clash && !confirm(`The last board configured from this browser, ${describeBoard(clash)}, is role ${clash.role || 'none'} and broadcasts ${hotspotForRole(cfg.role, shipRoles())}. `
      + `Saving role ${cfg.role || 'none'} here gives this board the same hotspot, and the two will ignore each other over BLE.\n\nSave the same role anyway?`)){
      log('ship settings not saved: same role as the last board'); return;
    }
    if(cfg.hotspot_open && !confirm('Run this ship\'s hotspot as an open network, with no password? Anyone nearby can join it.')){
      log('ship settings not saved'); return;
    }
    log(`writing ship settings: #${cfg.ship_id} ${cfg.ship_name}${cfg.role ? `, role ${cfg.role}` : ''}, hotspot ${hotspotSummary(cfg)}`);
    const written = await writeShipConfig(state.device, cfg);
    recordRole({ uid: state.deviceInfo?.uid || null, role: written.role, ship_id: written.ship_id, ship_name: written.ship_name });
    state.deviceInfo = { ...(state.deviceInfo || {}), ship: written };
    renderDeviceInfo(state.deviceInfo, { quiet: true });
    log('ship settings saved; they take effect when the ship restarts (Disconnect restarts it)');
  }catch(err){
    log(`ship settings not saved: ${err.message}`);
  }finally{
    setBusy(false);
  }
}

// ---------------------------------------------------------------- bench logs
function logPaths(){
  const installed = state.deviceInfo?.version?.version;
  const rel = installed ? state.releaseCache.get(installed) : null;
  return [...new Set([...(rel?.logs || []), ...DEFAULT_LOGS])];
}

async function refreshLogs(){
  if(!state.device) return;
  setBusy(true);
  try{
    state.logSizes = await statFiles(state.device, logPaths());
    els.logList.innerHTML = '';
    const present = Object.entries(state.logSizes).filter(([, size]) => size >= 0);
    if(!present.length){
      els.logList.innerHTML = '<li class="muted">No log files on this ship yet. The bench test writes its first row about a minute after boot.</li>';
    }
    for(const [path, size] of present){
      const li = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = path;
      const sz = document.createElement('span');
      sz.className = 'size';
      sz.textContent = size < 1024 ? `${size} B` : `${(size / 1024).toFixed(1)} KB`;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = 'Download';
      btn.addEventListener('click', () => downloadLogs([path]));
      li.append(name, sz, btn);
      els.logList.append(li);
    }
    log(`log files: ${present.map(([p, s]) => `${p} (${s} B)`).join(', ') || 'none'}`);
  }catch(err){
    log(`could not list logs: ${err.message}`);
  }finally{
    setBusy(false);
  }
}

async function downloadLogs(paths){
  if(!state.device) return;
  setBusy(true);
  resetProgress('Copying logs off the ship.', true);
  try{
    const list = paths || Object.entries(state.logSizes).filter(([, s]) => s >= 0).map(([p]) => p);
    if(!list.length) throw new Error('no log files listed; press Refresh list first');
    for(let i = 0; i < list.length; i++){
      const path = list[i];
      const size = state.logSizes[path];
      if(!(size >= 0)) continue;
      const bytes = await readFileBytes(state.device, path, size, {
        onProgress: ({ done, total }) => setProgress(((i + done / Math.max(1, total)) / list.length) * 100, `Reading ${path} · ${done}/${total} bytes`),
      });
      const name = logFileName(path, state.deviceInfo?.ship);
      saveBytes(bytes, name, path.endsWith('.txt') ? 'text/plain' : 'text/csv');
      log(`saved ${path} as ${name} (${bytes.length} B)`);
    }
    setProgress(100, 'Logs saved to your downloads folder.', 'complete');
  }catch(err){
    setProgress(100, `Log copy failed: ${err.message}`, 'failed');
    log(`log copy failed: ${err.message}`);
  }finally{
    setBusy(false);
  }
}

// ---------------------------------------------------------------- MicroPython runtime
function renderRuntimePanel(){
  const spec = state.runtime;
  if(!spec){ els.runtimeState.textContent = 'Runtime list unavailable.'; return; }
  const board = state.deviceInfo?.board;
  els.uf2List.innerHTML = '';
  const drives = [];
  for(const [id, b] of Object.entries(spec.boards || {})){
    drives.push(b.drive);
    const file = b.url.split('/').pop();
    const row = document.createElement('div');
    row.className = `uf2${board === id ? ' match' : ''}`;
    const info = document.createElement('div');
    const title = document.createElement('span');
    title.className = 'uf2-title';
    title.textContent = `${b.label} (${b.chip})${board === id ? ' · this board' : ''}`;
    const meta = document.createElement('small');
    meta.textContent = `${file} · ${(b.size / 1048576).toFixed(2)} MB`;
    const sha = document.createElement('code');
    sha.className = 'sha';
    sha.textContent = `sha256 ${b.sha256}`;
    sha.title = `Check it: ${Object.values(verifyCommands(file)).join('  |  ')}`;
    info.append(title, meta, sha);
    const a = document.createElement('a');
    a.href = b.url;
    a.rel = 'noopener';
    a.textContent = 'Download';
    row.append(info, a);
    els.uf2List.append(row);
  }
  els.driveNames.textContent = [...new Set(drives)].join(' or ');
  const release = state.releaseCache.get(state.selectedVersion);
  const st = runtimeStatus(spec, state.deviceInfo, release?.runtime?.min);
  const msg = {
    none: 'No runtime requirement.',
    unknown: `Ship software needs ${spec.name} ${st.need}. Connect a ship to check what it runs.`,
    ok: `This board runs ${spec.name} ${st.have}. Nothing to do here.`,
    newer: `This board runs ${spec.name} ${st.have}, newer than the tested ${spec.version}. It should work; reload ${spec.version} if anything misbehaves.`,
    old: `This board runs ${spec.name} ${st.have}; the selected release needs ${st.need} or newer. Load the runtime first.`,
  }[st.state];
  let cls = st.state === 'old' ? 'status-bad' : st.state === 'ok' ? 'status-ok' : 'status-warn';
  let text = msg;
  if(board && !boardSupported(spec, board)){
    text += ` Board ${board} is not a Pico W or Pico 2 W; the ships need the wireless chip.`;
    cls = 'status-bad';
  }
  els.runtimeState.textContent = text;
  els.runtimeState.className = `runtime-state ${cls}`;
}

async function enterBootsel(){
  if(!state.device) return;
  if(!confirm('Restart the board in BOOTSEL mode? It will appear as a USB drive and stop running its software until you copy a .uf2 onto it.')) return;
  const device = state.device;
  setBusy(true);
  state.device = null;
  await rebootToBootsel(device);
  state.deviceInfo = null;
  clearDeviceUi();
  setStatus('in BOOTSEL', 'status-warn');
  els.connectBtn.textContent = 'Connect ship';
  setBusy(false);
  log(`board is in BOOTSEL mode: download the .uf2 for it and drag it onto the ${els.driveNames.textContent} drive`);
}

// ---------------------------------------------------------------- install
async function refreshAfterInstall(){
  const device = state.device;
  log('waiting for the ship to restart');
  state.resetInProgress = true;
  await new Promise(resolve => setTimeout(resolve, 2200));
  try{
    await reconnectAfterReset(device, 12);
    log('ship reconnected; installed version refreshed');
  }catch(err){
    setStatus('reconnect needed', 'status-warn');
    log(`automatic reconnect failed; click Disconnect, then Connect (${err.message})`);
  }finally{
    state.resetInProgress = false;
  }
}

async function installVersion(version){
  if(!version){ log('no release selected'); return; }
  if(!state.device){ log('connect a ship first'); return; }
  setBusy(true);
  setStatus('installing', 'status-warn');
  resetProgress(`Preparing ${version}.`, true);
  try{
    const release = await getRelease(version);
    const info = state.deviceInfo || {};
    let clean = els.cleanInstall.checked;
    if(!clean && info.kind === 'other'){
      const names = (info.runtime?.root || []).filter(n => n !== 'data').join(', ');
      clean = confirm(`This board holds files from another project (${names}). Remove them first? data/ is kept either way. Cancel installs on top of them.`);
    }
    if(release.runtime?.min && info.runtime?.mpy && compareVersions(info.runtime.mpy, release.runtime.min) < 0){
      if(!confirm(`This board runs MicroPython ${info.runtime.mpy}, but ${version} needs ${release.runtime.min} or newer. Load the runtime first (section 3). Install anyway?`)){
        log('install cancelled: load the MicroPython runtime first'); resetProgress(); return;
      }
    }
    if(release.boards?.length && info.board && !release.boards.includes(info.board)){
      if(!confirm(`${version} is built for ${release.boards.join(' / ')}, but this board reports ${info.board}. Install anyway?`)){
        log('install cancelled'); resetProgress(); return;
      }
    }
    if(version !== state.index.latest && !confirm(`Install ${version}? Ship settings in data/ and the bench logs are kept.`)){
      log('install cancelled'); resetProgress(); return;
    }
    log(`installing ${version}${clean ? ' (clean: removing old files first)' : ''}`);
    await installRelease(state.device, release, {
      clean,
      onLog: log,
      onBeforeReset: () => { state.resetInProgress = true; },
      onProgress: ({ file, fileIndex, fileTotal, done, total }) => {
        const percent = ((fileIndex - 1) + (done / Math.max(1, total))) / Math.max(1, fileTotal) * 100;
        setProgress(percent, `Writing ${file.path} · chunk ${done}/${total}`);
        if(done === total) log(`verified ${file.path}`);
      },
    });
    setProgress(100, `${release.version} installed and verified.`, 'complete');
    await refreshAfterInstall();
    showPowerCycleModal();
  }catch(err){
    state.resetInProgress = false;
    setStatus('install failed', 'status-bad');
    setProgress(100, `Install failed: ${err.message}`, 'failed');
    log(`install failed: ${err.message}`);
  }finally{
    setBusy(false);
  }
}

// ---------------------------------------------------------------- wiring
function initEvents(){
  els.releaseSelect.addEventListener('change', () => {
    state.selectedVersion = els.releaseSelect.value || null;
    log(`selected release ${state.selectedVersion || 'none'}`);
    describeSelected();
  });
  els.connectBtn.addEventListener('click', () => { connectDevice(); });
  els.installLatestBtn.addEventListener('click', () => { installVersion(state.index?.latest); });
  els.installSelectedBtn.addEventListener('click', () => { installVersion(state.selectedVersion); });
  els.powerCycleDoneBtn.addEventListener('click', hidePowerCycleModal);
  els.powerCycleModal.addEventListener('click', event => { if(event.target === els.powerCycleModal) hidePowerCycleModal(); });
  document.addEventListener('keydown', event => { if(event.key === 'Escape' && !els.powerCycleModal.hidden) hidePowerCycleModal(); });
  els.saveShipBtn.addEventListener('click', () => { saveShipConfig(); });
  els.shipId.addEventListener('change', () => { els.shipName.placeholder = defaultShipName(els.shipId.value); });
  els.shipRole.addEventListener('change', renderShipSsid);
  els.shipShowPw.addEventListener('change', () => { els.shipPassword.type = els.shipShowPw.checked ? 'text' : 'password'; });
  els.shipOpen.addEventListener('change', () => { els.shipPassword.disabled = !state.device || els.shipOpen.checked; });
  els.refreshLogsBtn.addEventListener('click', () => { refreshLogs(); });
  els.downloadAllLogsBtn.addEventListener('click', () => { downloadLogs(null); });
  els.bootselBtn.addEventListener('click', () => { enterBootsel(); });
}

async function main(){
  if(!supportsWebSerial()){
    els.supportNotice.hidden = false;
    setStatus('browser not supported', 'status-bad');
    log('Web Serial is not available here; use desktop Chrome, Edge, Brave or Chromium');
  }else{
    setStatus('disconnected', 'status-warn');
    log('Web Serial available; plug in a ship over USB and click Connect ship');
  }
  initEvents();
  clearDeviceUi();
  setBusy(false);
  try{
    state.runtime = await loadRuntimeSpec();
    renderRuntimePanel();
  }catch(err){
    log(`runtime list unavailable: ${err.message}`);
  }
  try{
    renderIndex(await loadReleaseIndex());
  }catch(err){
    setText(els.latestVersion, 'unavailable');
    log(`could not load the release list: ${err.message}`);
  }
}
main();

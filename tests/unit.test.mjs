import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { compareVersions, latestVersion, isTestRelease } from '../src/releases.js';
import { validateShipConfig, SHIP_CONFIG_KEYS, defaultShipName, hotspotSummary, hotspotForRole, hotspotForRelease, shipNumberForRole } from '../src/ship-config.js';
import { logFileName } from '../src/device-logs.js';
import { runtimeStatus, boardSupported, verifyCommands } from '../src/runtime.js';
import { boardFromRuntime, firmwareKind, summarizeDeviceInfo, describeFirmware, overridesOf } from '../src/device-info.js';
import { findRelease, frozenMismatch } from '../src/installer.js';
import { CREW, validateCodes, sharedCodes, crewConfig, digest, randomCode, codeList, loadCodes, saveCodes, forgetCodes, CODES_MEMORY_KEY } from '../src/crew-codes.js';
import { loadRoleHistory, recordRole, suggestRole, roleClash, lastOtherBoard, ROLE_MEMORY_KEY } from '../src/role-memory.js';

let n = 0; const t = (name, fn) => { fn(); n++; console.log('ok -', name); };
const read = p => JSON.parse(readFileSync(new URL(`../${p}`, import.meta.url)));
const index = read('firmware/index.json');
const runtime = read('firmware/runtime.json');

t('compareVersions orders release > prerelease > older', () => {
  assert.ok(compareVersions('1.2.3', '1.2.3-coex') > 0);
  assert.ok(compareVersions('1.2.3-coex', '1.2.2') > 0);
  assert.ok(compareVersions('v0.3.16', '0.3.9') > 0);
  assert.equal(compareVersions('1.29.0', '1.29'), 0);
  assert.ok(compareVersions('1.28.0', '1.29.0') < 0);
});
t('static release index is Long Voyage only and points at release files', () => {
  assert.equal(index.project, 'LongVoyage');
  assert.ok(findRelease(index, index.latest), 'latest is listed');
  for(const r of index.releases) assert.match(r.path, /^\/firmware\/releases\/[^/]+\/release\.json$/);
});
t('ship config: WPA2 default, custom password, explicit open network', () => {
  const opts = { count: 8, roles: ['A', 'B'] };
  assert.equal(validateShipConfig({ ship_id: '8' }, opts).ship_id, 8, 'ship 8 (Marco) is valid');
  const def = validateShipConfig({ ship_id: '7', ship_name: ' Starship-07 ', hotspot_password: '', role: 'a' }, opts);
  assert.deepEqual({ ...def }, { schema: 2, ship_id: 7, ship_name: 'Starship-07', role: 'A', hotspot_open: false, led_notify: false });
  assert.equal(hotspotSummary(def), 'WPA2, firmware default password');
  assert.equal(validateShipConfig({ ship_id: 2, led_notify: 'on' }, opts).led_notify, true);
  const custom = validateShipConfig({ ship_id: 2, hotspot_password: 'correcthorse' }, opts);
  assert.equal(custom.hotspot_password, 'correcthorse');
  assert.equal(custom.ship_name, 'Starship-02');
  assert.equal(hotspotSummary(custom), 'WPA2, custom password');
  const open = validateShipConfig({ ship_id: 1, hotspot_open: true, hotspot_password: 'ignoredpw' }, opts);
  assert.equal(open.hotspot_open, true);
  assert.ok(!('hotspot_password' in open), 'open network carries no password');
  assert.equal(hotspotSummary(open), 'open network');
  assert.equal(hotspotSummary(null), 'firmware default (WPA2)');
  for(const bad of [{ ship_id: 9 }, { ship_id: 0 }, { ship_id: 1, hotspot_password: 'short' }, { ship_id: 1, ship_name: 'a"b' },
    { ship_id: 1, ship_name: 'x'.repeat(25) }, { ship_id: 1, role: 'C' }, { ship_id: 1, hotspot_password: 'x'.repeat(64) }]){
    assert.throws(() => validateShipConfig({ ship_name: 'S', hotspot_password: '', role: '', ...bad }, opts), JSON.stringify(bad));
  }
  assert.equal(defaultShipName(3), 'Starship-03');
});
t('ship config: fleet launch date (one flight day per real day from 06:00 that date)', () => {
  const opts = { count: 8, roles: [] };
  assert.equal(validateShipConfig({ ship_id: 1, launch_date: '2026-10-24' }, opts).launch_date, '2026-10-24');
  assert.equal(validateShipConfig({ ship_id: 1, launch_date: ' 2028-02-29 ' }, opts).launch_date, '2028-02-29', 'leap day');
  assert.ok(!('launch_date' in validateShipConfig({ ship_id: 1, launch_date: '' }, opts)), 'blank = the bench fixed day');
  for(const bad of ['2026-02-29', '2026-13-01', '24-10-2026', '2026-10-24T06:00', '1999-12-31', 'soon']){
    assert.throws(() => validateShipConfig({ ship_id: 1, launch_date: bad }, opts), bad);
  }
  assert.ok(SHIP_CONFIG_KEYS.includes('launch_date') && !SHIP_CONFIG_KEYS.includes('day'), 'the bench day is not the page\'s to drop');
});
t('log file names carry role, ship and UTC time', () => {
  const when = new Date('2026-10-22T21:05:00Z');
  assert.equal(logFileName('coex_log.csv', { role: 'A', ship_id: 3 }, when), 'coex_log_Aship3_20261022-2105.csv');
  assert.equal(logFileName('coex_boot.txt', null, when), 'coex_boot_20261022-2105.txt');
});
t('firmware kind: Long Voyage, hand-copied coex test, empty, other', () => {
  assert.equal(firmwareKind({ version: { project: 'LongVoyage', version: '0.0.1-coex' } }), 'long-voyage');
  assert.equal(firmwareKind({ runtime: { mainHead: '# Pico W / Pico 2 W Wi-Fi SoftAP + BLE coexistence soak test', root: ['main.py'] } }), 'long-voyage');
  assert.equal(firmwareKind({ runtime: { mainHead: '', root: ['boot.py', 'data'] } }), 'empty');
  assert.equal(firmwareKind({ version: { project: 'MarsHab' }, runtime: { root: ['main.py', 'server.py'] } }), 'other');
  assert.equal(summarizeDeviceInfo({ runtime: { mpy: '1.29.0', root: [] } }).version, 'nothing installed');
});
t('game firmware: frozen core described like the board, partial releases need their exact core', () => {
  const fz = { id: 'lv-core', version: '0.1.0', core: 'abcdef012345' };
  assert.equal(describeFirmware({ mpy: '1.29.0', root: [] }), 'stock MicroPython (no frozen game core)');
  assert.equal(describeFirmware({ frozen: fz, root: ['main.py', 'lvx'], lvx: ['engine.mpy', 'sync.py', '_x.py', 'notes.txt'] }),
    'frozen lv-core 0.1.0 (core abcdef012345), overrides: [engine, sync]');
  assert.match(describeFirmware({ frozen: fz, root: ['lv', 'main.py'], lvx: [] }), /HIDDEN by a \/lv directory/);
  assert.deepEqual(overridesOf({ lvx: ['engine.mpy', 'engine.py'] }), ['engine']);
  assert.match(summarizeDeviceInfo({ runtime: { mpy: '1.29.0', root: [], frozen: fz, lvx: [] } }).runtime, /^MicroPython 1\.29\.0 · game firmware: frozen lv-core/);
  assert.equal(summarizeDeviceInfo({ runtime: { mpy: '1.29.0', root: [] } }).runtime, 'MicroPython 1.29.0');
  const rel = { version: '0.1.1-x', frozen: { id: 'lv-core', version: '0.1.0', requires: 'abcdef012345' } };
  assert.equal(frozenMismatch({ version: '0.0.2' }, { mpy: '1.29.0' }), null, 'a full release goes anywhere');
  assert.equal(frozenMismatch(rel, { frozen: fz }), null);
  assert.match(frozenMismatch(rel, { mpy: '1.29.0' }), /stock MicroPython\. Flash lv-core-0\.1\.0-abcdef012345-<board>\.uf2 first/);
  assert.match(frozenMismatch(rel, { frozen: { ...fz, core: '111111111111' } }), /this board has lv-core 0\.1\.0 \(core 111111111111\)/);
  assert.match(frozenMismatch(rel, null), /could not be read/);
});
t('runtime: status, boards and upstream links', () => {
  assert.equal(runtimeStatus(runtime, { runtime: { mpy: '1.29.0' } }, '1.29.0').state, 'ok');
  assert.equal(runtimeStatus(runtime, { runtime: { mpy: '1.30.1' } }, '1.29.0').state, 'newer');
  assert.equal(runtimeStatus(runtime, { runtime: { mpy: '1.24.1' } }, '1.29.0').state, 'old');
  assert.equal(runtimeStatus(runtime, null, '1.29.0').state, 'unknown');
  assert.ok(boardSupported(runtime, 'RPI_PICO2_W')); assert.ok(!boardSupported(runtime, 'RPI_PICO'));
  assert.equal(boardFromRuntime({ machine: 'Raspberry Pi Pico 2 W with RP2350' }), 'RPI_PICO2_W');
  for(const b of Object.values(runtime.boards)){
    assert.match(b.url, /^https:\/\/micropython\.org\/resources\/firmware\/.+-v1\.29\.0\.uf2$/);
    assert.match(b.sha256, /^[0-9a-f]{64}$/);
  }
  assert.equal(verifyCommands('x.uf2').linux, 'sha256sum x.uf2');
});
t('hotspot name follows the role like the firmware (A -> COEX-0, B -> COEX-1, none -> COEX-0)', () => {
  assert.equal(hotspotForRole('A'), 'COEX-0');
  assert.equal(hotspotForRole('b'), 'COEX-1');
  assert.equal(hotspotForRole(''), 'COEX-0');
  assert.equal(hotspotForRole(null, ['A', 'B']), 'COEX-0');
  assert.equal(shipNumberForRole('A'), 1);
  assert.equal(shipNumberForRole('b'), 2);
  assert.equal(shipNumberForRole(''), null);
});
t('role memory: suggest the other role, warn on a repeat, tell boards apart by unique id', () => {
  const mem = new Map(); const storage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)) };
  const roles = ['A', 'B'];
  assert.deepEqual(loadRoleHistory(storage), []);
  assert.equal(suggestRole([], 'b1', roles), null, 'nothing to go on');
  recordRole({ uid: 'b1', role: 'A', ship_id: 1, ship_name: 'Starship-01', at: '2026-10-22T23:00:00Z' }, storage);
  let h = loadRoleHistory(storage);
  assert.equal(suggestRole(h, 'b2', roles), 'B', 'next board gets the other role');
  assert.equal(suggestRole(h, 'b1', roles), null, 'same board: no suggestion');
  assert.equal(roleClash(h, 'b2', 'A', roles)?.uid, 'b1', 'same role on another board warns');
  assert.equal(roleClash(h, 'b2', '', roles)?.uid, 'b1', 'no role is COEX-0 too, so it warns');
  assert.equal(roleClash(h, 'b2', 'B', roles), null);
  assert.equal(roleClash(h, 'b1', 'A', roles), null, 're-saving the same board never warns');
  recordRole({ uid: 'b2', role: 'B', ship_id: 2 }, storage);
  recordRole({ uid: 'b1', role: 'A', ship_id: 1 }, storage);
  h = loadRoleHistory(storage);
  assert.deepEqual(h.map(e => e.uid), ['b1', 'b2'], 'one entry per board, newest first');
  assert.equal(lastOtherBoard(h, 'b1').uid, 'b2');
  assert.equal(suggestRole(h, 'b3', roles), 'B');
  assert.equal(roleClash(h, null, 'A', roles)?.uid, 'b1', 'without a unique id every board counts as another');
  mem.set(ROLE_MEMORY_KEY, '{broken'); assert.deepEqual(loadRoleHistory(storage), [], 'corrupt storage is ignored');
  assert.deepEqual(loadRoleHistory(null), [], 'no storage at all');
});

// Crew codes: the browser must hash exactly like game/lv/codes.py (same vector as its tests).
const SALT = '000102030405060708090a0b0c0d0e0f';
const vec = await digest(SALT, 0, '1234');
const vec7 = await digest(SALT, 7, '3333');
const cfg = await crewConfig(['1234', '', '0420', '9999', '0000', '1111', '2222', '3333'], SALT);
t('crew codes: digest matches the board (game/lv/codes.py)', () => {
  assert.equal(vec, '0cc8d81bab788a28b5390ce71859e989a5b3e623b8e1cb44c6bfadccc5ff03e4');
  assert.equal(cfg.schema, 1);
  assert.equal(cfg.salt, SALT);
  assert.equal(cfg.codes[0], vec);
  assert.equal(cfg.codes[1], null, 'blank = not set up');
  assert.match(cfg.codes[2], /^[0-9a-f]{64}$/);
  assert.equal(cfg.codes.length, 8, 'eight crew, Marco last');
  assert.equal(vec7, '3c7e888a232925ef63cc815b1b52ca9e278224df35b7702bb77ed755dcd5f643', 'crew byte 7 (Marco), same as lv/codes.py');
  assert.equal(cfg.codes[7], vec7);
  assert.ok(!JSON.stringify(cfg).includes('0420'), 'no plain codes in the board file');
});
t('crew codes: roster matches game/content/roster.lv', () => {
  const lv = readFileSync(new URL('../game/content/roster.lv', import.meta.url), 'utf8');
  assert.deepEqual([...lv.matchAll(/^crew\s+(\S+)/gm)].map(m => m[1]), CREW);
});
t('crew codes: validation, shared codes, random codes, list, browser memory', () => {
  assert.deepEqual(validateCodes([' 1234', '', '0000', '', '', '', '', '']), ['1234', '', '0000', '', '', '', '', '']);
  assert.throws(() => validateCodes(['123', '', '', '', '', '', '', '']), /Phill's code must be 4 digits/);
  assert.throws(() => validateCodes(['', '12a4', '', '', '', '', '', '']), /Jacques/);
  assert.throws(() => validateCodes(['', '', '', '', '', '', '', '']), /at least one/);
  assert.throws(() => validateCodes(['1234']), /need 8/);
  assert.deepEqual(sharedCodes(['1234', '5678', '1234', '', '', '', '', '']), [['Phill', 'Kim']]);
  for(let i = 0; i < 200; i++) assert.match(randomCode(), /^\d{4}$/);
  assert.match(codeList(['1234', '', '', '', '', '', '', '']), /^Phill +1234\nJacques +\(not set up\)/);
  const mem = new Map(); const storage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v), removeItem: k => mem.delete(k) };
  assert.equal(loadCodes(storage), null);
  saveCodes({ salt: SALT, codes: ['1234', '', '', '', '', '', '', ''] }, storage);
  assert.deepEqual(loadCodes(storage).codes[0], '1234');
  mem.set(CODES_MEMORY_KEY, '{broken'); assert.equal(loadCodes(storage), null, 'corrupt storage is ignored');
  saveCodes({ salt: SALT, codes: ['1234', '', '', '', '', '', '', ''] }, storage); forgetCodes(storage);
  assert.equal(loadCodes(storage), null);
});
t('test channel: listed, never latest; stable untouched', () => {
  const rel = (version, channel) => ({ version, channel, path: `/firmware/releases/${version}/release.json` });
  const idx = { latest: '0.1.0-lv-test', releases: [rel('0.1.0-lv-test', 'test'), rel('0.0.2-coex', 'bench')] };
  assert.equal(latestVersion(idx), '0.0.2-coex', 'an index naming a test build as latest is overruled');
  assert.equal(latestVersion({ ...idx, releases: [...idx.releases, rel('0.0.1', 'stable')] }), '0.0.1', 'stable wins');
  assert.equal(latestVersion({ latest: null, releases: [rel('0.1.0-lv-test', 'test')] }), null, 'only test builds: no latest');
  assert.equal(latestVersion(index), index.latest, 'the published index already agrees');
  assert.ok(isTestRelease({ channel: 'test' }) && !isTestRelease({ channel: 'bench' }));
  for(const r of index.releases) if(r.channel === 'test') assert.notEqual(index.latest, r.version);
  assert.ok(compareVersions('0.1.0-lv-test', '0.0.2-coex') > 0, 'newer number, still not latest');
});
t('hotspot name from the release (game firmware) or the coex roles', () => {
  assert.equal(hotspotForRelease({ hotspot: { prefix: 'LV-' } }, { ship_id: 3 }), 'LV-3');
  assert.equal(hotspotForRelease({ hotspot: { prefix: 'LV-' } }, null), 'LV-1', 'no settings: ship 1');
  assert.equal(hotspotForRelease({}, { ship_id: 3 }), null);
  assert.equal(hotspotForRelease(undefined, { ship_id: 3 }), null);
});
console.log(`\n${n} unit checks passed`);

// End-to-end install against a simulated board (CPython standing in for MicroPython, see sim-device.mjs).
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { SimDevice } from './sim-device.mjs';
import { readDeviceInfo, summarizeDeviceInfo, describeFirmware } from '../src/device-info.js';
import { installRelease } from '../src/installer.js';
import { validateShipConfig, writeShipConfig } from '../src/ship-config.js';
import { statFiles, readFileBytes } from '../src/device-logs.js';
import { crewConfig, writeCrewConfig, newSalt } from '../src/crew-codes.js';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..');
const index = JSON.parse(readFileSync(join(repo, 'firmware/index.json'), 'utf8'));
const voyage = JSON.parse(readFileSync(join(repo, index.releases.find(r => r.version === index.latest).path.slice(1)), 'utf8'));
const log = process.env.VERBOSE ? m => console.log('   ', m) : () => {};
let pass = 0;
async function t(name, fn){ await fn(); pass++; console.log('ok -', name); }

// A board that still runs some other project (here: an old Mars Habitat install), with saved data and a bench log.
const root = mkdtempSync(join(tmpdir(), 'simboard-'));
mkdirSync(join(root, 'data'));
mkdirSync(join(root, 'www'));
writeFileSync(join(root, 'config.py'), 'FIRMWARE_VERSION = "0.3.16"\nHAB = 1\n');
writeFileSync(join(root, 'main.py'), 'print("other project")\n');
writeFileSync(join(root, 'server.py'), '# old\n');
writeFileSync(join(root, 'www/app.js'), '//old\n');
writeFileSync(join(root, 'data/save.json'), '{"turn":12}');
const csv = Buffer.from('t,boot,heap\n' + Array.from({ length: 400 }, (_, i) => `${i},1,${100000 - i}`).join('\n') + '\n');
writeFileSync(join(root, 'coex_log.csv'), csv);
const dev = new SimDevice(root);

await t('reads a board running another project', async () => {
  const info = await readDeviceInfo(dev);
  assert.equal(info.board, 'RPI_PICO_W');
  assert.equal(info.runtime.mpy, '1.29.0');
  assert.equal(info.kind, 'other');
  assert.equal(summarizeDeviceInfo(info).version, 'other firmware');
});

await t('tells two boards apart by machine.unique_id()', async () => {
  assert.equal((await readDeviceInfo(dev)).uid, 'e6614c311b2a3d2f');
  const other = await readDeviceInfo(new SimDevice(root, { uid: 'e6614c31aa55aa55' }));
  assert.equal(other.uid, 'e6614c31aa55aa55');
  assert.match(summarizeDeviceInfo(other).board, /id e6614c31aa55aa55$/);
});

await t('clean install of the latest release over a foreign board', async () => {
  await installRelease(dev, voyage, { clean: true, onLog: log });
  const files = readdirSync(root).sort();
  assert.deepEqual(files, ['coex_log.csv', 'config.py', 'data', 'index.html', 'main.py', 'version.json']);
  for(const f of voyage.files){
    const got = createHash('sha256').update(readFileSync(join(root, f.path))).digest('hex');
    assert.equal(got, f.sha256, f.path);
  }
  assert.equal(readFileSync(join(root, 'data/save.json'), 'utf8'), '{"turn":12}', 'data/ kept');
  assert.deepEqual(readFileSync(join(root, 'coex_log.csv')), csv, 'bench log kept');
  assert.ok(!existsSync(join(root, 'secrets.py')));
  assert.ok(dev.resets >= 1, 'board reset after install');
});

await t('recognises Long Voyage after install', async () => {
  const info = await readDeviceInfo(dev);
  assert.equal(info.kind, 'long-voyage');
  assert.equal(summarizeDeviceInfo(info).version, voyage.version);
});

await t('ship config written atomically and read back', async () => {
  const cfg = validateShipConfig({ ship_id: '3', ship_name: 'Starship-03', hotspot_password: 'correcthorse', role: 'B' }, { count: 8, roles: ['A', 'B'] });
  await writeShipConfig(dev, cfg);
  const info = await readDeviceInfo(dev);
  assert.equal(info.ship.ship_id, 3);
  assert.equal(info.ship.role, 'B');
  assert.ok(!existsSync(join(root, 'data/ship.tmp')));
  await writeShipConfig(dev, { ...cfg, ship_name: 'Starship-03b' });
  assert.ok(existsSync(join(root, 'data/ship.bak')));
});

await t('saving ship settings keeps the bench day and other board keys; launch date set and cleared', async () => {
  const path = join(root, 'data/ship.json');
  const before = JSON.parse(readFileSync(path, 'utf8'));
  writeFileSync(path, JSON.stringify({ ...before, day: 9, day_start: '21:30', fleet_key: 'k', launch_date: '2026-10-01' }));
  const opts = { count: 8, roles: ['A', 'B'] };
  await writeShipConfig(dev, validateShipConfig({ ship_id: 3, ship_name: 'Starship-03b', hotspot_password: 'correcthorse', role: 'B', launch_date: '2026-10-24' }, opts));
  let on = JSON.parse(readFileSync(path, 'utf8'));
  assert.deepEqual([on.day, on.day_start, on.fleet_key, on.launch_date, on.ship_id], [9, '21:30', 'k', '2026-10-24', 3]);
  await writeShipConfig(dev, validateShipConfig({ ship_id: 3, ship_name: 'Starship-03b', hotspot_password: 'correcthorse', role: 'B' }, opts));
  on = JSON.parse(readFileSync(path, 'utf8'));
  assert.equal(on.day, 9, 'the bench day survives a save');
  assert.ok(!('launch_date' in on), 'a cleared launch date is removed');
  // The board reads it: no launch date -> the manual day.
  const r = spawnSync('python3', ['-c', 'import sys; sys.path[:0] = [sys.argv[1], sys.argv[1] + "/.."]; import lvship; c = lvship.load_config(sys.argv[2]); print(c["day"], repr(c["launch_date"]))',
    join(repo, 'game', 'board'), path], { encoding: 'utf8' });
  assert.equal(r.stdout.trim(), "9 ''", r.stderr);
});

await t('crew codes written to data/crew.json and accepted by the game core', async () => {
  const cfg = await crewConfig(['1234', '', '0420', '9999', '0000', '1111', '2222', '3333'], newSalt());
  await writeCrewConfig(dev, cfg);
  assert.ok(!existsSync(join(root, 'data/crew.tmp')));
  const onBoard = JSON.parse(readFileSync(join(root, 'data/crew.json'), 'utf8'));
  assert.deepEqual(onBoard.codes, cfg.codes);
  // The board side (game/lv/codes.py) reads the same file: right code OK, wrong code counted, blank not set up.
  const r = spawnSync('python3', ['-c',
    'import json,sys; sys.path.insert(0, sys.argv[1]); from lv import codes as K\n' +
    'b = K.CodeBook(json.load(open(sys.argv[2])))\n' +
    'print(b.check(0, "1234", 0), b.check(2, "0420", 0), b.check(0, "4321", 0), b.check(1, "1234", 0), b.check(7, "3333", 0))',
    join(repo, 'game'), join(root, 'data/crew.json')], { encoding: 'utf8' });
  assert.equal(r.stdout.trim(), '(0, 0) (0, 0) (1, 4) (3, 0) (0, 0)', r.stderr);
  await writeCrewConfig(dev, cfg);   // overwriting is fine too
});

// Load the installed config.py with /data/ mapped into the sim board.
function loadConfig(){
  const r = spawnSync('python3', ['-c',
    'import builtins; _o = open; builtins.open = lambda p, *a, **k: _o(p[1:] if p.startswith("/data/") else p, *a, **k)\n' +
    'import config as C; print(C.SHIP_ID, C.SHIP_NUM, C.SHIP_NAME, "open" if not C.AP_PASSWORD else len(C.AP_PASSWORD))'], { cwd: root, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  return r.stdout.trim();
}

await t('firmware applies data/ship.json: custom WPA2 password', async () => {
  assert.equal(loadConfig(), '1 3 Starship-03b 12');
});

await t('firmware keeps its WPA2 default when no password is set', async () => {
  await writeShipConfig(dev, validateShipConfig({ ship_id: 4, role: 'A' }, { count: 8, roles: ['A', 'B'] }));
  assert.equal(loadConfig(), '0 4 Starship-04 9');
});

await t('firmware opens the hotspot only when asked explicitly', async () => {
  await writeShipConfig(dev, validateShipConfig({ ship_id: 4, role: 'A', hotspot_open: true }, { count: 8, roles: ['A', 'B'] }));
  assert.equal(loadConfig(), '0 4 Starship-04 open');
});

await t('firmware still boots with a corrupt ship.json', async () => {
  writeFileSync(join(root, 'data/ship.json'), '{not json');
  assert.match(loadConfig(), / 9$/);
  await writeShipConfig(dev, validateShipConfig({ ship_id: 3, role: 'B', hotspot_password: 'correcthorse' }, { count: 8, roles: ['A', 'B'] }));
});

await t('reinstall (not clean) keeps ship config and logs', async () => {
  await installRelease(dev, voyage, { onLog: log });
  assert.equal(JSON.parse(readFileSync(join(root, 'data/ship.json'), 'utf8')).ship_id, 3);
  assert.deepEqual(readFileSync(join(root, 'coex_log.csv')), csv);
});

await t('pulls a log file byte-exact', async () => {
  const sizes = await statFiles(dev, ['coex_log.csv', 'coex_log.old', 'coex_boot.txt']);
  assert.equal(sizes['coex_log.csv'], csv.length);
  assert.equal(sizes['coex_log.old'], -1);
  const bytes = await readFileBytes(dev, 'coex_log.csv', sizes['coex_log.csv']);
  assert.deepEqual(Buffer.from(bytes), csv);
});

await t('a tampered release is rejected before touching the board', async () => {
  const bad = structuredClone(voyage);
  bad.files.find(x => x.path === 'main.py').sha256 = '0'.repeat(64);
  const before = readFileSync(join(root, 'main.py'));
  const execs = dev.execs;
  await assert.rejects(installRelease(dev, bad, { onLog: log }), /sha256|hash/i);
  assert.deepEqual(readFileSync(join(root, 'main.py')), before);
  assert.equal(dev.execs, execs, 'no device command ran');
});

await t('the test build installs by hand over a coex board, and the coex release brings it back', async () => {
  // A named release (LV_TEST_RELEASE=0.3.0-ota-phone), else the test channel's head, else the
  // newest test entry: the suite checks the build it's meant to, not whatever is listed first.
  const want = process.env.LV_TEST_RELEASE || index.channels?.test;
  const entry = (want && index.releases.find(r => r.version === want)) || index.releases.find(r => r.channel === 'test');
  assert.ok(entry, 'a test release is listed');
  if (process.env.LV_TEST_RELEASE) assert.equal(entry.version, process.env.LV_TEST_RELEASE, 'the named test release is listed');
  assert.equal(entry.channel, 'test');
  assert.notEqual(index.latest, entry.version, 'the test build is not latest');
  const test = JSON.parse(readFileSync(join(repo, entry.path.slice(1)), 'utf8'));
  assert.equal(test.hotspot?.prefix, 'LV-');
  assert.ok(!test.files.some(f => /(^|\/)(ship\.json|season_log\.bin)$/.test(f.path)), 'no device-local or test-only files');
  // A partial release for the game firmware: stock MicroPython is refused before anything is written.
  assert.ok(test.frozen?.requires, 'the test build names its frozen core');
  const execs = dev.execs, before = readFileSync(join(root, 'main.py'));
  await assert.rejects(installRelease(dev, test, { onLog: log }), /needs the game firmware .* stock MicroPython/);
  assert.equal(dev.execs, execs + 1, 'only the firmware check ran');
  assert.deepEqual(readFileSync(join(root, 'main.py')), before);
  const fwDev = new SimDevice(root, { frozen: `${test.frozen.id}:${test.frozen.version}:${test.frozen.requires}` });
  await installRelease(fwDev, test, { onLog: log });
  assert.match(summarizeDeviceInfo(await readDeviceInfo(fwDev)).runtime, /game firmware: frozen lv-core \S+ \(core [0-9a-f]{12}\), overrides: \[/);
  assert.ok(!existsSync(join(root, 'lv')), 'no /lv on a game-firmware board');
  assert.ok(!existsSync(join(root, 'config.py')) && !existsSync(join(root, 'index.html')), 'coex files removed');
  for(const f of test.files){
    const got = createHash('sha256').update(readFileSync(join(root, f.path))).digest('hex');
    assert.equal(got, f.sha256, f.path);
  }
  const v = JSON.parse(readFileSync(join(root, 'version.json'), 'utf8'));
  assert.equal(v.version, entry.version); assert.equal(v.channel, 'test');
  assert.equal(JSON.parse(readFileSync(join(root, 'data/ship.json'), 'utf8')).ship_id, 3, 'ship settings kept');
  assert.deepEqual(readFileSync(join(root, 'coex_log.csv')), csv, 'bench log kept');
  await installRelease(fwDev, voyage, { onLog: log });
  assert.equal(JSON.parse(readFileSync(join(root, 'version.json'), 'utf8')).version, index.latest, 'rolled back to latest');
  const main = voyage.files.find(f => f.path === 'main.py');
  assert.equal(createHash('sha256').update(readFileSync(join(root, 'main.py'))).digest('hex'), main.sha256);
});

// Partial releases: built against one frozen core, shipping overrides of only the changed modules.
const tree = mkdtempSync(join(tmpdir(), 'partial-'));
for(const d of ['firmware', 'src', 'src-board/lvx', 'src-board/www']) mkdirSync(join(tree, d), { recursive: true });
for(const f of ['index.html', 'styles.css', 'favicon.svg', 'src/main.js']) writeFileSync(join(tree, f), '');
writeFileSync(join(tree, 'firmware/runtime.json'), readFileSync(join(repo, 'firmware/runtime.json')));
const coreJson = join(tree, 'core.json');
writeFileSync(coreJson, JSON.stringify({ id: 'lv-core', version: '9.9.9', core: 'abcdef012345', micropython: 'v1.29.0',
  modules: ['lv', 'lv.engine', 'lv.engage', 'lv.sync'], sha256: {} }));
const sb = join(tree, 'src-board');
writeFileSync(join(sb, 'main.py'), 'print("game")\n');
writeFileSync(join(sb, 'lvship.mpy'), Buffer.from([77, 6, 0, 31]));
writeFileSync(join(sb, 'www/app.html.gz'), Buffer.from([31, 139, 8, 0]));
writeFileSync(join(sb, 'lvx/engine.mpy'), Buffer.from([77, 6, 0, 31, 1]));
const build = (version, extra = []) => spawnSync('python3', [join(repo, 'tools/build_release.py'), '--repo-root', tree, '--version', version,
  '--channel', 'test', '--label', 'partial', '--source', sb, '--build-time', '2026-10-23T00:00:00+00:00', ...extra], { encoding: 'utf8' });
const validate = () => spawnSync('python3', [join(repo, 'tools/validate_firmware.py'), '--root', tree], { encoding: 'utf8' });
const relOf = v => join(tree, 'firmware/releases', v, 'release.json');

await t('partial release: builder ships only lvx/ overrides of frozen modules, validator agrees', async () => {
  let r = build('9.9.9-p1', ['--frozen', coreJson]);
  assert.equal(r.status, 0, r.stderr + r.stdout);
  const rel = JSON.parse(readFileSync(relOf('9.9.9-p1'), 'utf8'));
  assert.equal(rel.frozen.requires, 'abcdef012345');
  assert.deepEqual(rel.overrides, ['engine']);
  assert.ok(rel.delete.includes('lv') && rel.delete.includes('lvx'), 'clears lv/ and old overrides first');
  // 0.3.0 R1: a --frozen build deletes the coex bench's config.py and index.html by default
  assert.ok(rel.delete.includes('config.py') && rel.delete.includes('index.html'), 'clears the coex bench files by default');
  assert.equal(JSON.parse(readFileSync(join(tree, 'firmware/index.json'), 'utf8')).releases[0].frozen, 'abcdef012345');
  r = validate();
  assert.equal(r.status, 0, r.stdout);
  assert.match(r.stdout, /partial: lv-core core abcdef012345, overrides \[engine\]/);
  // Without a frozen core an lvx/ override would be ignored on the board: refused.
  r = build('9.9.9-p2');
  assert.notEqual(r.status, 0); assert.match(r.stderr, /only work on the game firmware/);
  // An override of a module the core doesn't have, or a whole lv/: refused.
  writeFileSync(join(sb, 'lvx/nosuch.mpy'), 'x');
  r = build('9.9.9-p2', ['--frozen', coreJson]);
  assert.notEqual(r.status, 0); assert.match(r.stderr, /only hold overrides of the frozen modules/);
  rmSync(join(sb, 'lvx/nosuch.mpy'));
  mkdirSync(join(sb, 'lv')); writeFileSync(join(sb, 'lv/engine.mpy'), 'x');
  r = build('9.9.9-p2', ['--frozen', coreJson]);
  assert.notEqual(r.status, 0); assert.match(r.stderr, /must not ship lv\//);
  rmSync(join(sb, 'lv'), { recursive: true });
});

await t('validator catches a hand-edited partial release', async () => {
  const good = readFileSync(relOf('9.9.9-p1'), 'utf8');
  const edits = [
    [rel => { rel.delete = rel.delete.filter(d => d !== 'lv'); }, /must delete lv before installing/],
    [rel => { rel.overrides = []; }, /overrides \[\] != lvx\/ files \['engine'\]/],
    [rel => { rel.frozen.modules = ['sync']; }, /lvx\/engine.mpy is not an override of a frozen module/],
    [rel => { rel.frozen.requires = 'nope'; }, /12-hex core hash/],
    [rel => { delete rel.frozen; delete rel.overrides; }, /ships lvx\/ overrides but names no frozen core/],
  ];
  for(const [edit, want] of edits){
    const rel = JSON.parse(good); edit(rel);
    writeFileSync(relOf('9.9.9-p1'), JSON.stringify(rel));
    const r = validate();
    assert.notEqual(r.status, 0, 'should fail: ' + want);
    assert.match(r.stdout, want);
  }
  writeFileSync(relOf('9.9.9-p1'), good);
  assert.equal(validate().status, 0);
});

await t('partial release installs only on its own core: stale /lv and old overrides go, describe shows the overrides', async () => {
  const rel = JSON.parse(readFileSync(relOf('9.9.9-p1'), 'utf8'));
  const board = mkdtempSync(join(tmpdir(), 'fwboard-'));
  mkdirSync(join(board, 'data')); mkdirSync(join(board, 'lv')); mkdirSync(join(board, 'lvx'));
  writeFileSync(join(board, 'data/ship.json'), '{"ship_id":2}');
  writeFileSync(join(board, 'lv/engine.mpy'), 'stale full install');
  writeFileSync(join(board, 'lvx/sync.mpy'), 'an older override');
  writeFileSync(join(board, 'main.py'), 'old');
  const other = new SimDevice(board, { frozen: 'lv-core:9.9.9:000000000000' });
  assert.match(describeFirmware((await readDeviceInfo(other)).runtime), /HIDDEN by a \/lv directory/);
  await assert.rejects(installRelease(other, rel, { onLog: log }), /needs the game firmware lv-core 9\.9\.9 \(core abcdef012345\); this board has lv-core 9\.9\.9 \(core 000000000000\)/);
  assert.equal(readFileSync(join(board, 'main.py'), 'utf8'), 'old', 'nothing written');
  const fw = new SimDevice(board, { frozen: 'lv-core:9.9.9:abcdef012345' });
  await installRelease(fw, rel, { onLog: log });
  assert.ok(!existsSync(join(board, 'lv')), 'stale /lv removed');
  assert.deepEqual(readdirSync(join(board, 'lvx')), ['engine.mpy'], 'only the shipped override');
  assert.equal(readFileSync(join(board, 'data/ship.json'), 'utf8'), '{"ship_id":2}');
  const info = await readDeviceInfo(fw);
  assert.equal(describeFirmware(info.runtime), 'frozen lv-core 9.9.9 (core abcdef012345), overrides: [engine]');
  assert.equal(JSON.parse(readFileSync(join(board, 'version.json'), 'utf8')).frozen, 'abcdef012345');
});

console.log(`\n${pass} integration checks passed (board dir ${root})`);

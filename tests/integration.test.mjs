// End-to-end install against a simulated board (CPython standing in for MicroPython, see sim-device.mjs).
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { SimDevice } from './sim-device.mjs';
import { readDeviceInfo, summarizeDeviceInfo } from '../src/device-info.js';
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
  const cfg = validateShipConfig({ ship_id: '3', ship_name: 'Starship-03', hotspot_password: 'correcthorse', role: 'B' }, { count: 7, roles: ['A', 'B'] });
  await writeShipConfig(dev, cfg);
  const info = await readDeviceInfo(dev);
  assert.equal(info.ship.ship_id, 3);
  assert.equal(info.ship.role, 'B');
  assert.ok(!existsSync(join(root, 'data/ship.tmp')));
  await writeShipConfig(dev, { ...cfg, ship_name: 'Starship-03b' });
  assert.ok(existsSync(join(root, 'data/ship.bak')));
});

await t('crew codes written to data/crew.json and accepted by the game core', async () => {
  const cfg = await crewConfig(['1234', '', '0420', '9999', '0000', '1111', '2222'], newSalt());
  await writeCrewConfig(dev, cfg);
  assert.ok(!existsSync(join(root, 'data/crew.tmp')));
  const onBoard = JSON.parse(readFileSync(join(root, 'data/crew.json'), 'utf8'));
  assert.deepEqual(onBoard.codes, cfg.codes);
  // The board side (game/lv/codes.py) reads the same file: right code OK, wrong code counted, blank not set up.
  const r = spawnSync('python3', ['-c',
    'import json,sys; sys.path.insert(0, sys.argv[1]); from lv import codes as K\n' +
    'b = K.CodeBook(json.load(open(sys.argv[2])))\n' +
    'print(b.check(0, "1234", 0), b.check(2, "0420", 0), b.check(0, "4321", 0), b.check(1, "1234", 0))',
    join(repo, 'game'), join(root, 'data/crew.json')], { encoding: 'utf8' });
  assert.equal(r.stdout.trim(), '(0, 0) (0, 0) (1, 4) (3, 0)', r.stderr);
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
  await writeShipConfig(dev, validateShipConfig({ ship_id: 4, role: 'A' }, { count: 7, roles: ['A', 'B'] }));
  assert.equal(loadConfig(), '0 4 Starship-04 9');
});

await t('firmware opens the hotspot only when asked explicitly', async () => {
  await writeShipConfig(dev, validateShipConfig({ ship_id: 4, role: 'A', hotspot_open: true }, { count: 7, roles: ['A', 'B'] }));
  assert.equal(loadConfig(), '0 4 Starship-04 open');
});

await t('firmware still boots with a corrupt ship.json', async () => {
  writeFileSync(join(root, 'data/ship.json'), '{not json');
  assert.match(loadConfig(), / 9$/);
  await writeShipConfig(dev, validateShipConfig({ ship_id: 3, role: 'B', hotspot_password: 'correcthorse' }, { count: 7, roles: ['A', 'B'] }));
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

console.log(`\n${pass} integration checks passed (board dir ${root})`);

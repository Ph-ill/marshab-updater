// The phone's side of tests/test_ota_step.py: the real phone pages (0.3.0's web/ota.js, this
// branch's, and the duel build's) in a JS VM, against a simulated ship running the real
// updater on the lv32 build (tests/mp_ota_step.py) and a stand-in GitHub (fixture folders).
// Each scenario starts from a fresh copy of a 0.3.0 ship's flash, checks for updates,
// installs, restarts the ship and reloads the page the ship then serves, the way a phone
// would. Timers run on a fake clock, only once nothing is in flight.
//
//   node tests/ota_step_page.mjs <config.json> <scenario>
//
// Prints one JSON line, {"scenario", "heap": {"peak", "sig", "sig_samples"}, "puts", "boots", "notes"}, when it passes.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { spawn, spawnSync } from 'node:child_process';
import { readFileSync, cpSync, rmSync, readdirSync, statSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

const [cfgPath, scenario] = process.argv.slice(2);
const cfg = JSON.parse(readFileSync(cfgPath, 'utf8'));
const { STEP, DUEL } = cfg;
const OLD = '0.3.0';
const heap = { peak: 0, sig: 0, sig_samples: 0 };
const notes = [];
const note = (s) => { notes.push(s); };

// ---- the ship -----------------------------------------------------------------------------
const flash = cfg.flash;
const readJSON = (p) => { try { return JSON.parse(readFileSync(join(flash, p), 'utf8')); } catch { return null; } };
const installed = () => readJSON('version.json').version;
function peak(o) {
  assert.ok(o.peak > 0);
  heap.peak = Math.max(heap.peak, o.peak);
  if (o.sig_samples) { heap.sig = Math.max(heap.sig, o.sig); heap.sig_samples += o.sig_samples; }
}
// Every file on flash but the update's own working space and the ship's data, by hash.
function snapshot() {
  const out = {};
  const walk = (d) => {
    for (const n of readdirSync(join(flash, d))) {
      const p = d ? d + '/' + n : n;
      if (p === 'ota' || p === 'data') continue;
      if (statSync(join(flash, p)).isDirectory()) walk(p);
      else out[p] = createHash('sha256').update(readFileSync(join(flash, p))).digest('hex');
    }
  };
  walk('');
  return out;
}
const ship = {
  proc: null, lines: null, waiting: [], restart: false, plan: [], boots: [],
  // One boot: boot.py (lvboot), then main.py; good = it came up and kept the update.
  boot(cut = 0, good = true) {
    const r = spawnSync(cfg.micropython, ['-X', 'heapsize=160k', cfg.runner, 'boot', String(cut), good ? '1' : '0'], { cwd: flash, encoding: 'utf8' });
    assert.equal(r.status, 0, `boot failed:\n${r.stdout}\n${r.stderr}`);
    const o = JSON.parse(r.stdout.trim().split('\n').pop());
    peak(o); this.boots.push({ cut, good, ...o });
    if (o.max_files != null) assert.equal(o.max_files, cfg.limits[o.v], `${o.v} runs with its own updater`);
    return o;
  },
  async on() {
    assert.ok(!this.proc);
    const v = installed();
    assert.ok(cfg.limits[v], `a known version on flash: ${v}`);
    this.proc = spawn(cfg.micropython, ['-X', 'heapsize=160k', cfg.runner, 'serve', String(cfg.limits[v])], { cwd: flash });
    this.err = '';
    this.proc.stderr.on('data', (d) => { this.err += d; });
    this.lines = createInterface({ input: this.proc.stdout });
    this.lines.on('line', (l) => {
      if (!/^[[{]/.test(l)) { this.err += l + '\n'; return; }      // a traceback: the exit reports it
      const w = this.waiting.shift(); assert.ok(w, 'an answer nobody asked for: ' + l); w[0](l);
    });
    this.proc.once('exit', () => { for (const w of this.waiting.splice(0)) w[1](new Error('ship exited: ' + this.err)); });
    const ready = await this.read();
    assert.deepEqual(JSON.parse(ready), { ready: true }, this.err);
  },
  read() { return new Promise((ok, no) => { this.waiting.push([ok, no]); }); },
  async ask(m, p, q, b) {
    this.proc.stdin.write(JSON.stringify({ m, p, q, b: b ? Buffer.from(b).toString('hex') : '' }) + '\n');
    return JSON.parse(await this.read());
  },
  // Power off (a cut, or the restart after apply): the server's own heap peaks are kept.
  async off() {
    if (!this.proc) return;
    const p = this.proc;
    this.proc = null;
    const done = new Promise((ok) => p.once('exit', ok));
    const w = new Promise((ok, no) => this.waiting.push([ok, no]));
    p.stdin.write('quit\n');
    const l = await w;
    await done;
    assert.equal(p.exitCode, 0, this.err);
    peak(JSON.parse(l));
  },
};

// ---- the stand-in GitHub ------------------------------------------------------------------
const gh = { index: cfg.index, online: true, got: [] };
function github(url) {
  const m = /^https:\/\/raw\.githubusercontent\.com\/[^/]+\/[^/]+\/main(\/firmware\/.+)$/.exec(url);
  assert.ok(m, 'a release URL on main: ' + url);
  gh.got.push(m[1]);
  const p = join(cfg.gh, gh.index, m[1]);
  return existsSync(p) ? response(JSON.parse(readFileSync(p, 'utf8'))) : response({}, 404);
}
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });

// ---- the phone ----------------------------------------------------------------------------
let store = null;                // localStorage, one origin: kept across pages and reloads
let now = 1.9e12;
const timers = new Map();
let nextId = 0, inflight = 0;
const puts = [];
const faults = [];               // the harness's own failures inside a page's fetch (it would swallow them)
let cutAt = 0;                   // the power goes right after the ship writes this put (1-based)
const shipFetch = async (url, o = {}) => {
  if (url.startsWith('https://')) {
    if (!gh.online) throw new TypeError('Failed to fetch');
    return github(url);
  }
  const [path, qs] = url.split('?');
  if (ship.restart && path === '/api/ota') {
    // the ship restarted after apply: it boots as many times as the plan says (power cuts,
    // a game that never calls good()), then serves again
    ship.restart = false;
    for (const [cut, good] of ship.plan) ship.boot(cut, good);
    ship.plan = [];
    await ship.on();
  }
  if (!ship.proc) throw new TypeError('Failed to fetch');
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  const m = (o.method || 'GET');
  if (path === '/api/ota/put') puts.push(q);
  const [s, j] = await ship.ask(m, path, q, o.body);
  if (path === '/api/ota/put' && cutAt && puts.length === cutAt) {
    cutAt = 0;
    await ship.off();
    throw new TypeError('Failed to fetch');            // written, but the answer never came
  }
  if (path === '/api/ota/apply' && s === 200) {
    await ship.off();                                 // lvota.restart: about a second later
    ship.restart = true;
  }
  return response(j, s);
};
function page(file) {
  const src = readFileSync(file, 'utf8'), el = {};
  const c = vm.createContext({
    AbortController, TypeError, SyntaxError, atob, TextEncoder, Uint8Array, JSON,
    Date: class extends Date { constructor(...a) { super(...(a.length ? a : [now])); } static now() { return now; } },
    localStorage: { getItem: () => store, setItem(k, v) { store = v; } },
    setTimeout(fn, ms) { timers.set(++nextId, { fn, at: now + (ms || 0) }); return nextId; },
    clearTimeout(id) { timers.delete(id); },
    fetch: async (url, o) => {
      inflight++;
      try { return await shipFetch(url, o); } catch (e) { if (!(e instanceof TypeError)) faults.push(e); throw e; } finally { inflight--; }
    },
    route: 'set', home() {}, refresh: async () => {}, go() {}, view() {},
    h: (s) => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    shipTop() {}, scrollTo() {}, dock() {}, $: (id) => (el[id] ||= {}), tok: 'crew-token',
    document: { addEventListener() {}, hidden: false, querySelector: () => null },
    addEventListener() {}, location: { reload() {} },
  });
  vm.runInContext(src, c);
  const run = (s) => vm.runInContext(s, c);
  return {
    run,
    // a page call that awaits: the fake clock moves only while nothing is in flight
    async call(s) {
      let done = false, err = null, val;
      vm.runInContext(s, c).then((v) => { val = v; done = true; }, (e) => { err = e; done = true; });
      for (let spin = 0; !done; spin++) {
        await new Promise((ok) => setImmediate(ok));
        if (done || inflight) continue;
        await new Promise((ok) => setImmediate(ok));
        if (done || inflight) continue;
        const t = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
        if (!t) continue;
        timers.delete(t[0]);
        now = Math.max(now, t[1].at);
        t[1].fn();
        assert.ok(spin < 1e6, 'the page settles');
      }
      if (faults.length) throw faults[0];
      if (err) throw err;
      return val;
    },
    settings: () => run('otaSect()'),
    screen() { run('otaScreen()'); return el.v.innerHTML; },
    b: () => JSON.parse(run('JSON.stringify(OB||otaLoad())')),
    oi: () => JSON.parse(run('JSON.stringify(OI)')),
    os: () => JSON.parse(run('JSON.stringify(OS_)')),
  };
}
const squeeze = (s) => s.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('//')).join('\n');
// The page this ship serves now: the phone reloads it after the restart. Its www/app.html.gz
// must carry that release's own otaCheck (web/build.py inlines ota.js into it).
function served() {
  const v = installed(), src = readFileSync(cfg.pages[v], 'utf8');
  const html = gunzipSync(readFileSync(join(flash, 'www/app.html.gz'))).toString();
  const fn = src.slice(src.indexOf('async function otaCheck('), src.indexOf('// ---- installing'));
  assert.ok(fn.length > 500 && html.includes(squeeze(fn)), `the ship on ${v} serves ${cfg.pages[v]}`);
  return page(cfg.pages[v]);
}
async function aboard(p) {
  await p.call('otaStatus()');
  return p.os();
}
async function check(p, force = true) {
  gh.online = true; gh.got = [];
  await p.call(`otaCheck(${force})`);
  return p.b();
}
// Install what the page offers. plan: the boots after apply, [cut after N moves, good()].
async function install(p, plan = [[0, true]]) {
  ship.plan = plan; gh.online = false;
  const n = puts.length;
  await p.call('otaInstall()');
  return { oi: p.oi(), puts: puts.slice(n), screen: p.screen() };
}
const files = (v) => JSON.parse(readFileSync(join(cfg.gh, 'good/firmware/releases', v, 'release.json'), 'utf8'));
// the pieces of an install: the envelope, then each file, 1024 B each (the ship's chunk)
const pieces = (v) => {
  const env = JSON.stringify(files(v).ota), m = JSON.parse(files(v).ota.m);
  return Math.ceil(Buffer.byteLength(env) / 1024) + m.files.reduce((s, f) => s + Math.max(1, Math.ceil(f[1] / 1024)), 0);
};
function restoredTo(snap, v, what) {
  assert.equal(installed(), v, what + ': version');
  assert.deepEqual(snapshot(), snap, what + ': every file as it was');
  assert.equal(readJSON('ota/state.json'), null, what + ': nothing pending');
  assert.equal(existsSync(join(flash, 'ota/old')), false, what + ': rollback copies cleared');
}
function sentinel() {
  assert.ok(readFileSync(join(flash, 'data/sentinel.bin')).equals(Buffer.from([...Array(256).keys()])), 'data/ untouched');
}

// The real chain: a 0.3.0 phone page installs the stepping stone; the page the ship then
// serves finds the duel build and installs it.
async function chain(p0) {
  let st = await aboard(p0);
  assert.equal(st.v, OLD); assert.equal(st.ch, 'test');
  let b = await check(p0);
  assert.equal(b.rel && b.rel.v, STEP, 'a 0.3.0 page (channels) is offered the stepping stone');
  assert.deepEqual(gh.got, ['/firmware/index.json', `/firmware/releases/${STEP}/release.json`]);
  let r = await install(p0);
  assert.equal(r.oi.ok, true, 'stepping stone installed: ' + r.oi.msg);
  assert.equal(r.puts.length, pieces(STEP), 'every piece sent once');
  assert.equal(installed(), STEP);
  sentinel();
  const p1 = served();
  st = await aboard(p1);
  assert.equal(st.v, STEP); assert.equal(st.last.result, 'installed');
  // not forced: the check the 0.3.0 page made doesn't count for this one (b.hd)
  b = await check(p1, false);
  assert.equal(b.rel && b.rel.v, DUEL, 'the stepping stone page finds the duel build (heads)');
  assert.equal(b.rel.next, '', 'nothing after it');
  assert.deepEqual(gh.got, ['/firmware/index.json', `/firmware/releases/${DUEL}/release.json`]);
  r = await install(p1);
  assert.equal(r.oi.ok, true, 'duel installed: ' + r.oi.msg);
  assert.equal(installed(), DUEL);
  return served();
}

const scenarios = {
  async chain() {
    const p2 = await chain(page(cfg.pages[OLD]));
    const st = await aboard(p2);
    assert.equal(st.v, DUEL);
    const b = await check(p2);
    assert.equal(p2.run('otaFor(OS_)'), null, 'nothing more offered');
    assert.match(p2.settings(), /Up to date/);
    note('0.3.0 page -> ' + STEP + ' -> ' + STEP + ' page -> ' + DUEL + '; then up to date (seen ' + b.seen + ')');
  },
  // This branch's page in a tab on a 0.3.0 ship (or any page from 0.3.1-updater on, there):
  // it's offered the stepping stone, says why, and finds the duel once it's in.
  async newpage() {
    const p = page(cfg.pages[STEP]);
    await aboard(p);
    let b = await check(p);
    assert.equal(b.rel.v, STEP); assert.equal(b.rel.next, DUEL); assert.equal(b.seen, DUEL);
    assert.deepEqual(gh.got, ['/firmware/index.json', `/firmware/releases/${STEP}/release.json`], 'the duel release is never fetched for it');
    const s = p.settings();
    assert.ok(s.includes(`Your ship needs this update before it can take ${DUEL}. Once it has restarted, check for updates again to get ${DUEL}.`), s);
    const r = await install(p);
    assert.equal(r.oi.ok, true, r.oi.msg);
    assert.ok(r.screen.includes(`Your ship can take ${DUEL} now. Check for updates again while you have internet to get it.`), r.screen);
    assert.equal(p.b().at, 0, 'the next chance to check is taken');
    await aboard(p);
    assert.match(p.settings(), new RegExp(`${DUEL.replaceAll('.', '\\.')} \\(check again to get it\\)`));
    b = await check(p, false);
    assert.equal(b.rel.v, DUEL, 'online again: the duel, without waiting six hours');
    const r2 = await install(p);
    assert.equal(r2.oi.ok, true, r2.oi.msg);
    assert.equal(installed(), DUEL);
    sentinel();
  },
  // An index published by hand with channels on the duel build: a 0.3.0 page can't be
  // fixed, and shows the ship's own words; the validator is what stops this index.
  async badold() {
    gh.index = 'bad';
    const p = page(cfg.pages[OLD]);
    await aboard(p);
    const b = await check(p);
    assert.equal(b.rel.v, DUEL);
    const snap = snapshot();
    const r = await install(p);
    assert.equal(r.oi.ok, false);
    assert.equal(r.oi.msg, 'bad file list', 'the 0.3.0 page shows the raw refusal');
    assert.ok(r.puts.every((q) => q.f === '0'), 'only the signature was sent');
    assert.equal(r.puts.filter((q) => q.f === '0' && q.o === '0').length, 1, 'sent once: no loop');
    assert.equal(timers.size, 0, 'nothing scheduled to try again');
    restoredTo(snap, OLD, 'refused');
  },
  async badnew() {
    gh.index = 'bad';
    const p = page(cfg.pages[STEP]);
    await aboard(p);
    const b = await check(p);
    assert.equal(b.rel.v, DUEL); assert.equal(b.rel.next, '');
    const snap = snapshot();
    const r = await install(p);
    assert.equal(r.oi.ok, false);
    assert.equal(r.oi.msg, "Your ship needs an earlier update before it can take this one. Check for updates again while you have internet, and install the update you're offered first.");
    assert.equal(r.puts.filter((q) => q.f === '0' && q.o === '0').length, 1, 'sent once: no loop');
    assert.ok(r.puts.every((q) => q.f === '0'), 'no file sent after the refusal');
    assert.equal(timers.size, 0, 'nothing scheduled to try again');
    restoredTo(snap, OLD, 'refused');
    assert.equal(p.os().v, OLD);
  },
  // Power cuts and a failed trial, on the stepping stone's swap (from 0.3.0) and then on
  // the duel's (from the stepping stone).
  async faults() {
    for (const [v, from] of [[STEP, OLD], [DUEL, STEP]]) {
      const p = served();
      await aboard(p);
      assert.equal((await check(p)).rel.v, v);
      const snap = snapshot(), total = pieces(v);
      // 1. a trial that fails: the game never calls good(). The third boot rolls back, the
      //    power goes during that rollback, and the next boot finishes it.
      let r = await install(p, [[0, false], [0, false], [3, false], [0, true]]);
      assert.equal(r.oi.ok, false, `${v} on trial, never kept`);
      assert.equal(r.oi.msg, `It didn't start, so your ship went back to ${from}.`);
      const bs = ship.boots.slice(-4);
      assert.deepEqual(bs.map((x) => x.state ? x.state.phase : null), ['trial', 'trial', 'undo', null], 'trial, trial, cut in the rollback, rolled back');
      assert.deepEqual(bs.slice(0, 2).map((x) => x.state.boots), [1, 2]);
      assert.equal(bs[2].cut, true);
      assert.equal(bs[3].last.result, 'rolled back');
      assert.equal(bs[3].good, false, 'nothing left to keep');
      assert.equal(bs[3].max_files, cfg.limits[from], 'the old updater is back');
      restoredTo(snap, from, 'rolled back');
      sentinel();
      // 2. the power goes during the download, right after the ship wrote a piece
      cutAt = puts.length + Math.floor(total / 2);
      r = await install(p);
      assert.equal(r.oi.ok, false, 'cut during the download');
      assert.equal(installed(), from);
      ship.boot(0, true);
      await ship.on();
      const st = await aboard(p);
      assert.equal(st.staged && st.staged.v, v, 'what was written is still staged');
      // 3. Install again: it carries on from what the ship has (the same envelope, by hash),
      //    and the power goes during the swap, after 5 moves; the next boot finishes it.
      r = await install(p, [[5, true], [0, true]]);
      assert.equal(r.oi.ok, true, `resumed and installed ${v}: ${r.oi.msg}`);
      assert.ok(r.puts.length < total - 2, `resumed (${r.puts.length} of ${total} pieces)`);
      assert.equal(r.puts.filter((q) => q.f === '0').length, 0, "the signature isn't sent again");
      const [cut, back] = ship.boots.slice(-2);
      assert.equal(cut.cut, true); assert.equal(cut.moves, 5);
      assert.equal(back.last.result, 'installed'); assert.equal(back.good, true);
      assert.equal(back.max_files, cfg.limits[v], `${v}'s own updater runs`);
      assert.equal(installed(), v);
      sentinel();
      note(`${v}: failed trial rolled back (cut in the rollback), download cut and resumed, swap cut and finished`);
    }
  },
};
function reset() { rmSync(flash, { recursive: true, force: true }); cpSync(cfg.pristine, flash, { recursive: true }); }

reset();
await ship.on();
try {
  await scenarios[scenario]();
} finally {
  await ship.off().catch(() => {});
}
assert.ok(heap.peak > 0 && heap.peak < cfg.cap, `heap ${heap.peak} B under ${cfg.cap} B`);
assert.ok(heap.sig_samples > 0 && heap.sig > 0, 'sampled inside the signature check');
console.log(JSON.stringify({ scenario, heap, puts: puts.length, boots: ship.boots.length, notes }));

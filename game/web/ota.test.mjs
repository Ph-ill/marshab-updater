// Phone-only OTA checks. No board, signing, network or third-party dependencies.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./ota.js', import.meta.url), 'utf8');
const ship = { ch: 'test', core: 'core1', v: '0.3.0' };
const entry = { version: '0.3.1', channel: 'test', ota: 'test-key', frozen: 'core1', path: '/firmware/0.3.1/release.json', notes: ['Your update notes.'] };
const index = () => ({ channels: { test: entry.version }, releases: [structuredClone(entry)] });
// Deliberately a shape-only fixture, not a signed release. Authenticity remains the ship's job.
const release = () => ({ ota: { kid: 'test-key', sig: Buffer.alloc(64).toString('base64'), m: JSON.stringify({ schema: 1, project: 'LongVoyage', version: entry.version, channel: 'test', core: 'core1', files: [['app.html.gz', 3, 'a'.repeat(64)]] }) }, files: [{ path: 'app.html.gz', data: 'YWJj' }] });
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
function phone(fetcher, saved = ship, store = () => true) {
  let value = JSON.stringify(saved), next = 0, now = 1000000;
  const timers = new Map(), calls = [], paints = [], listeners = {};
  const c = vm.createContext({
    AbortController, TypeError, SyntaxError, atob, TextEncoder, Uint8Array,
    Date: class extends Date { static now() { return now; } },
    localStorage: { getItem: () => value, setItem(k, v) { if (!store(JSON.parse(v))) throw new Error('quota'); value = v; } },
    setTimeout(fn, ms) { timers.set(++next, { fn, ms }); return next; },
    clearTimeout(id) { timers.delete(id); },
    fetch: async (url, opts) => { calls.push({ url, opts }); return fetcher(url, opts, calls.length); },
    route: 'set', home() {}, refresh: async () => {}, view() { paints.push(vm.runInContext('otaSect()', c)); },
    h: (s) => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    shipTop() {}, scrollTo() {}, dock() {}, $: () => ({}), tok: 'test-token',
    document: { addEventListener(k, fn) { listeners[k] = fn; }, hidden: false },
    addEventListener(k, fn) { listeners[k] = fn; },
  });
  const run = (s) => vm.runInContext(s, c);
  run(source); c.ship = ship; run('OS_=ship');
  return { c, run, calls, paints, timers, listeners,
    state: () => JSON.parse(run('JSON.stringify(OB)')),
    stored: () => JSON.parse(value),
    advance: (ms) => { now += ms; },
    fire(ms) { const t = [...timers].find(([, t]) => t.ms === ms); assert.ok(t, `timer ${ms} exists`); timers.delete(t[0]); t[1].fn(); },
  };
}
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const good = (url) => response(url.endsWith('index.json') ? index() : release());

// Adapted from review_phone_probes.mjs: run against this checkout, with fixed expectations.
function historyHTML(p) {
  const el = {}; p.c.$ = () => el; p.run('otaHist()'); return el.innerHTML;
}
test('review: configured branch supplies index, release and history', async () => {
  const p = phone(good, { ...ship, src: 'ota-hwfix-030' });
  p.run("OS_={...ship,src:'ota-hwfix-030'}");
  await p.run('otaCheck(true)'); await p.run('otaHistOpen()');
  assert.equal(p.calls.length, 3);
  assert.ok(p.calls.every(({ url }) => url.startsWith('https://raw.githubusercontent.com/Ph-ill/marshab-updater/ota-hwfix-030/')));
});
test('review: real repository index retains missing installed release and baked notes', async () => {
  const idx = JSON.parse(readFileSync(new URL('../../firmware/index.json', import.meta.url), 'utf8'));
  const wn = JSON.parse(readFileSync(new URL('../tools/ota/whatsnew.json', import.meta.url), 'utf8'));
  const p = phone(() => response(idx)); p.c.wn = wn;
  p.run("OS_={...ship,v:'0.3.0-ota-phone'};Object.assign(OTA_WN,wn)");
  await p.run('otaHistOpen()');
  const rows = JSON.parse(p.run('JSON.stringify(OH.list)'));
  assert.deepEqual(rows.find((e) => e.v === '0.3.0-ota-phone').n, wn['0.3.0-ota-phone']);
  assert.match(historyHTML(p), /Installed/);
});
test('review: all 14 releases remain visible, including the oldest installed release', async () => {
  const releases = Array.from({ length: 14 }, (_, n) => ({ version: '0.3.' + n, channel: 'test', notes: ['notes'] }));
  const p = phone(() => response({ releases })); await p.run('otaHistOpen()');
  assert.equal(p.run('OH.list.length'), 14);
  assert.equal(p.run('OH.list[13].v'), ship.v);
  assert.match(historyHTML(p), /Installed/);
});
test('history retains Installed and Ready without notes, whether indexed or missing', async () => {
  for (const indexed of [false, true]) {
    const rel = { v: '0.3.1', ch: ship.ch, core: ship.core, notes: [] };
    const releases = indexed ? [ship.v, rel.v].map((version) => ({ version, channel: ship.ch })) : [];
    const p = phone(() => response({ releases }), { ...ship, rel });
    await p.run('otaHistOpen()');
    assert.equal(p.run('OH.list.length'), 2);
    const html = historyHTML(p);
    assert.match(html, /Installed/); assert.match(html, /Ready to install/);
    assert.equal((html.match(/No notes for this version/g) || []).length, 2);
  }
});
test('history fills missing index notes locally without replacing published notes or duplicating rows', async () => {
  for (const notes of [[], ['Published notes']]) {
    const p = phone(() => response({ releases: [{ version: ship.v, channel: ship.ch, notes }] }));
    p.run("OTA_WN[ship.v]=['Baked notes']");
    await p.run('otaHistOpen()');
    assert.equal(p.run('OH.list.length'), 1);
    assert.equal(p.run('OH.list[0].n[0]'), notes[0] || 'Baked notes');
  }
});

test('review: history preserves HTTP 404/500 status without suggesting a network switch', async () => {
  for (const status of [404, 500]) {
    const p = phone(() => response({}, status));
    p.run("OTA_WN[ship.v]=['Local notes kept']");
    await p.run('otaHistOpen()');
    assert.equal(p.run('OH.st'), 'off'); assert.equal(p.run('OH.err'), 'http');
    assert.equal(p.run('OH.http'), status);
    const html = historyHTML(p);
    assert.ok(html.includes(`HTTP ${status}`));
    assert.match(html, /Local notes kept/); assert.match(html, /Installed/);
    assert.doesNotMatch(html, /mobile data|another Wi-Fi|couldn't reach|timed out/);
    assert.equal(p.timers.size, 0);
  }
});
test('history identifies invalid JSON and index data while keeping installed notes', async () => {
  const bad = [
    ...[null, {}, { releases: null }, { releases: {} }, { releases: 'bad' }].map((data) => () => response(data)),
    () => ({ ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } }),
  ];
  for (const fetcher of bad) {
    const p = phone(fetcher); p.run("OTA_WN[ship.v]=['Local notes kept']");
    await p.run('otaHistOpen()');
    assert.equal(p.run('OH.err'), 'bad');
    const html = historyHTML(p);
    assert.match(html, /version history data is invalid/); assert.match(html, /Local notes kept/);
    assert.doesNotMatch(html, /mobile data|another Wi-Fi|HTTP|couldn't reach/);
    assert.equal(p.timers.size, 0);
  }
});
test('history reserves network advice for reachability and distinguishes timeout', async () => {
  for (const timeout of [false, true]) {
    const p = phone((url, { signal }) => {
      if (!timeout) throw new TypeError('unreachable');
      return { ok: true, json: () => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))) };
    });
    p.run("OTA_WN[ship.v]=['Local notes kept']");
    const pending = p.run('otaHistOpen()');
    if (timeout) { await flush(); p.fire(8000); }
    await pending;
    assert.equal(p.run('OH.err'), timeout ? 'timeout' : 'network');
    const html = historyHTML(p);
    assert.match(html, timeout ? /request timed out/ : /couldn't reach GitHub/);
    assert.match(html, /mobile data or another Wi-Fi network/);
    assert.match(html, /Local notes kept/); assert.equal(p.timers.size, 0);
  }
});
test('history retry clears the previous failure and restores online rows', async () => {
  let fail = true;
  const p = phone(() => fail ? response({}, 404) : response(index()));
  await p.run('otaHistOpen()'); assert.equal(p.run('OH.http'), 404);
  fail = false; await p.run('otaHistOpen()');
  assert.equal(p.run('OH.st'), 'on'); assert.equal(p.run('OH.err'), undefined);
  assert.doesNotMatch(historyHTML(p), /HTTP|invalid|another Wi-Fi/);
});

test('successful download persists on this phone, keeps notes, and never asks the offline ship', async () => {
  const p = phone(good);
  await p.run('otaCheck(true)');
  assert.equal(p.state().ok, true);
  assert.equal(p.stored().rel.v, entry.version);
  assert.deepEqual(p.stored().rel.notes, entry.notes);
  assert.equal(p.calls.length, 2);
  assert.ok(p.calls.every(({ url }) => url.startsWith('https://raw.githubusercontent.com/')));
  assert.match(p.run('otaSect()'), /ready on this phone/);
  assert.match(p.run('otaSect()'), /What's new/);
  assert.equal(p.timers.size, 0);
});

test('network error retries once after 1.5 s, serializes all triggers and paints Checking throughout', async () => {
  const p = phone(() => { throw new TypeError('unreachable'); });
  const pending = p.run('otaCheck(true)'); await flush();
  assert.equal(p.calls.length, 1);
  assert.match(p.run('otaSect()'), /data-ota=check disabled aria-busy=true/);
  assert.match(p.run('otaSect()'), /Checking…/);
  await p.run('otaCheck(true)'); p.listeners.online(); p.listeners.visibilitychange();
  assert.equal(p.calls.length, 1);
  p.advance(40000);
  assert.equal(p.run('otaChecking()'), true);
  p.fire(1500); await pending;
  assert.equal(p.calls.length, 2);
  assert.equal(p.state().err, 'network');
  assert.equal(p.state().ok, false);
  assert.equal(p.run('otaChecking()'), false);
  assert.equal(p.timers.size, 0);
  const html = p.run('otaSect()');
  assert.match(html, /Your phone couldn't reach GitHub on this network\./);
  assert.match(html, /Couldn't check/);
  assert.doesNotMatch(html, /Up to date|no internet/);
  assert.ok(html.indexOf('data-ota=check') < html.indexOf('Turn Wi-Fi off'));
  for (const text of ['move away from your ship', "Don't close it or switch to Safari; its storage is separate.", 'ready on this phone', "rejoin your ship's network, then tap Install."]) assert.ok(html.includes(text));
});

test('index deadline covers the body, retries once and reports timeout separately', async () => {
  const p = phone((url, { signal }) => ({ ok: true, json: () => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('body aborted')))) }));
  const pending = p.run('otaCheck(true)'); await flush();
  p.fire(8000); await flush(); p.fire(1500); await flush(); p.fire(8000); await pending;
  assert.equal(p.state().err, 'timeout');
  assert.match(p.run('otaSect()'), /Your update check timed out\. You can try again\./);
  assert.match(p.run('otaSect()'), /otasteps/);
  assert.equal(p.calls.length, 2);
  assert.equal(p.timers.size, 0);
});

test('release body has 30 seconds, not the 8-second index deadline; retry recovers', async () => {
  let bodies = 0;
  const p = phone((url, { signal }) => {
    if (url.endsWith('index.json')) return response(index());
    if (++bodies === 1) return { ok: true, json: () => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('body aborted')))) };
    return response(release());
  });
  const pending = p.run('otaCheck(true)'); await flush();
  assert.deepEqual([...p.timers.values()].map((t) => t.ms), [30000]);
  p.fire(30000); await flush(); p.fire(1500); await pending;
  assert.equal(bodies, 2);
  assert.equal(p.state().err, '');
  assert.equal(p.stored().rel.v, entry.version);
});

test('retry budget is shared by index and release failures', async () => {
  const p = phone((url, opts, n) => { if (n === 1 || !url.endsWith('index.json')) throw new TypeError('unreachable'); return response(index()); });
  const pending = p.run('otaCheck(true)'); await flush(); p.fire(1500); await pending;
  assert.equal(p.calls.length, 3);
  assert.equal(p.state().err, 'network');
  assert.equal(p.timers.size, 0);
});

test('HTTP statuses are reported without retry or network instructions', async () => {
  for (const status of [403, 404, 429, 500, 503]) {
    const p = phone(() => response(null, status)); await p.run('otaCheck(true)');
    assert.equal(p.calls.length, 1);
    assert.equal(p.state().err, 'http');
    assert.ok(p.run('otaSect()').includes(`You couldn't get the update from GitHub (HTTP ${status}). Try again later.`));
    assert.doesNotMatch(p.run('otaSect()'), /otasteps|no internet/);
  }
});

test('bad JSON, index, envelope, signature shape and incomplete file data are not network failures', async () => {
  const bad = [
    () => response(null), () => response({}), () => response({ channels: [], releases: [] }),
    () => response({ channels: { test: entry.version }, releases: [] }),
    () => { const idx = index(); delete idx.releases[0].ota; return response(idx); },
    () => ({ ok: true, json: async () => { throw new SyntaxError('JSON'); } }),
    ...[
      (r) => { delete r.ota; }, (r) => { r.ota.sig = ''; }, (r) => { r.ota.m = '{}'; },
      (r) => { r.ota.m = 'null'; }, (r) => { r.files = []; }, (r) => { r.files[0].data = '!'; },
      (r) => { r.files[0].data = 'YQ=='; }, (r) => { r.files.push(r.files[0]); },
      (r) => { const m = JSON.parse(r.ota.m); m.channel = 'other'; r.ota.m = JSON.stringify(m); },
    ].map((mutate) => (url) => { const r = release(); mutate(r); return response(url.endsWith('index.json') ? index() : r); }),
  ];
  for (const fetcher of bad) {
    const p = phone(fetcher); await p.run('otaCheck(true)');
    assert.equal(p.state().err, 'bad'); assert.equal(p.timers.size, 0);
    assert.match(p.run('otaSect()'), /Your update data is invalid or missing a signature\. Try again later\./);
    assert.doesNotMatch(p.run('otaSect()'), /otasteps|no internet/);
    assert.ok(!p.stored().rel);
  }
});

test('storage full does not claim ready or discard a previously cached update', async () => {
  const p = phone(good, ship, (b) => !b.rel); await p.run('otaCheck(true)');
  assert.equal(p.state().err, 'full'); assert.equal(p.state().ok, false);
  assert.ok(!p.state().rel); assert.ok(!p.stored().rel);
  assert.match(p.run('otaSect()'), /Your phone couldn't store the update\. Free some phone storage, then try again\./);
  assert.doesNotMatch(p.run('otaSect()'), /ready on this phone|otasteps/);
  const old = { v: '0.3.0-old', ch: 'test', core: 'core1', notes: ['Kept.'], bytes: 3 };
  const q = phone(good, { ...ship, rel: old }, (b) => !b.rel || b.rel.v === old.v); await q.run('otaCheck(true)');
  assert.deepEqual(q.stored().rel, old); assert.deepEqual(q.state().rel, old);
  const blocked = phone(good, ship, () => false); await blocked.run('otaCheck(true)');
  assert.equal(blocked.state().err, 'full'); assert.equal(blocked.run('otaChecking()'), false);
});

test('automatic failure backoff is two minutes; manual checks bypass it, success waits six hours', async () => {
  const p = phone(() => response(null, 503)); await p.run('otaCheck(false)');
  await p.run('otaCheck(false)'); assert.equal(p.calls.length, 1);
  await p.run('otaCheck(true)'); assert.equal(p.calls.length, 2);
  p.advance(119999); await p.run('otaCheck(false)'); assert.equal(p.calls.length, 2);
  p.advance(1); await p.run('otaCheck(false)'); assert.equal(p.calls.length, 3);
  const q = phone(good); await q.run('otaCheck(false)');
  q.advance(6 * 3600e3 - 1); await q.run('otaCheck(false)'); assert.equal(q.calls.length, 2);
  q.advance(1); await q.run('otaCheck(false)'); assert.equal(q.calls.length, 3);
});

test('old errors clear during checking; cached notes refresh without another release download', async () => {
  const p = phone(good, { ...ship, at: 1, ok: false, err: 'offline' });
  const pending = p.run('otaCheck(true)');
  assert.doesNotMatch(p.run('otaSect()'), /otasteps|couldn't reach/); await pending;
  await p.run('otaCheck(true)');
  assert.equal(p.calls.length, 3); assert.deepEqual(p.state().rel.notes, entry.notes);
  p.c.offline = { ...ship, at: 2, ok: false, err: 'offline' }; p.run('OB=offline');
  assert.match(p.run('otaSect()'), /otasteps/);
});

test('manual click completes without an offline /api/ota request; install busy message and cancel stay intact', async () => {
  const p = phone(good);
  const button = { disabled: false, dataset: { ota: 'check' } };
  await p.listeners.click({ target: { closest: () => button } });
  assert.equal(p.calls.length, 2);
  assert.equal(p.run('otaWhy(409,{err:"busy, on trial"})'), 'Your ship is still checking its last update. Try again in a couple of minutes.');
  await p.run('otaCancel()');
  assert.equal(p.calls.at(-1).url, '/api/ota/cancel');
  assert.equal(p.calls.at(-1).opts.method, 'POST');
  p.run('OTA_BUSY=true'); await p.run('otaCheck(true)'); assert.equal(p.calls.length, 3);
});

test('version history still loads and escapes release notes', async () => {
  const p = phone((url) => { const idx = index(); idx.releases[0].notes = ['<script>bad</script>']; return response(idx); });
  await p.run('otaHistOpen()');
  assert.equal(p.run('OH.st'), 'on');
  assert.match(p.run('otaNotes(OH.list[0].n)'), /&lt;script&gt;/);
});

test('latest failure replaces stale Up to date, but an update already on the phone stays installable', async () => {
  const p = phone(() => response(null, 503), { ...ship, seen: ship.v, at: 1, ok: true });
  assert.match(p.run('otaSect()'), /Up to date/);
  await p.run('otaCheck(true)');
  assert.match(p.run('otaSect()'), /Couldn't check/);
  assert.doesNotMatch(p.run('otaSect()'), /Up to date/);
  const q = phone(good); await q.run('otaCheck(true)');
  const reopened = phone(() => response(null, 503), q.stored());
  await reopened.run('otaCheck(true)');
  assert.match(reopened.run('otaSect()'), /ready on this phone/);
  assert.match(reopened.run('otaSect()'), /data-ota=install>/);
  assert.deepEqual(reopened.stored().rel, q.stored().rel);
});

test('a successful index can report Up to date or an incompatible core without downloading', async () => {
  for (const [v, core] of [[ship.v, ship.core], [entry.version, 'other-core']]) {
    const p = phone(() => response({ channels: { test: v }, releases: [{ ...entry, version: v, frozen: core }] }));
    // Keep the installed entry cached: the original behavior may download it otherwise.
    if (v === ship.v) { p.c.saved = { ...ship, rel: { v, ch: ship.ch, core, bytes: 3 } }; p.run('otaSave(saved)'); }
    await p.run('otaCheck(true)');
    assert.equal(p.state().ok, true); assert.equal(p.calls.length, 1);
    assert.match(p.run('otaSect()'), v === ship.v ? /Up to date/ : /not signed for this ship/);
  }
});

// 0.3.0 review 2 M4: the ship's admission 503 (Retry-After: 1) means "busy, try again",
// never "this ship needs a USB install". Timers here are fake: drain() fires each pause.
const busy = () => ({ ok: false, status: 503, headers: { get: (k) => (k === 'Retry-After' ? '1' : null) }, json: async () => ({ err: 'busy, try again' }) });
async function drain(p, promise) {
  let done = false, out; promise.then((v) => { done = true; out = v; }, (e) => { done = true; out = e; });
  for (let i = 0; i < 200 && !done; i++) { await flush(); const t = [...p.timers][0]; if (t && !done) { p.timers.delete(t[0]); p.advance(t[1].ms); t[1].fn(); } }
  assert.ok(done, 'settled'); return out;
}
test('review2 M4: /api/ota busy is replayed, then the status lands', async () => {
  const p = phone((url, o, n) => (n <= 3 ? busy() : response({ ...ship, v: '0.3.0', chunk: 512 })));
  p.run('OS_=null');
  const st = await drain(p, p.run('otaStatus()'));
  assert.equal(p.calls.length, 4); assert.equal(st.chunk, 512);
  assert.equal(p.run('OTA_NONE'), false);
  assert.doesNotMatch(p.run('otaSect()'), /USB/);
});
test('review2 M4: a failed /api/ota keeps the last status; only 404 says USB', async () => {
  const p = phone(() => response({ err: 'no memory' }, 503));
  const st = await drain(p, p.run('otaStatus()'));
  assert.equal(st, null);
  assert.equal(p.run('OS_.v'), ship.v);
  assert.doesNotMatch(p.run('otaSect()'), /USB/);
  p.run('OS_=null'); assert.doesNotMatch(p.run('otaSect()'), /USB/);
  const q = phone(() => response({ err: 'no such thing' }, 404)); q.run('OS_=null');
  await drain(q, q.run('otaStatus()'));
  assert.equal(q.run('OTA_NONE'), true); assert.match(q.run('otaSect()'), /USB/);
});
test('review2 M4: an upload piece rides out admission 503s past the old four tries', async () => {
  const p = phone((url, o, n) => (n <= 7 ? busy() : response({ have: 4 })));
  const [s, j] = await drain(p, p.run('otaPut("f=1&o=0",new Uint8Array(4))'));
  assert.equal(s, 200); assert.equal(j.have, 4); assert.equal(p.calls.length, 8);
  const q = phone(() => busy());
  const r = await drain(q, q.run('otaPut("f=1&o=0",new Uint8Array(4))'));
  assert.equal(r[0], 503, 'gives up after the replay window, without a USB message');
  assert.doesNotMatch(q.run('otaWhy(503,{})'), /USB/);
});

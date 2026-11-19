// Cancel hail (0.3.8) in the hail menu and on the home card, without a browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./live.js', import.meta.url), 'utf8');

function phone({live, api} = {}) {
  const listeners = [];
  const nodes = {};
  const el = (id) => {
    if (!nodes[id]) nodes[id] = {id, innerHTML: '', outerHTML: '', insertAdjacentHTML() {}};
    return nodes[id];
  };
  const calls = [];
  const c = vm.createContext({
    tok: 'tok',
    N: 8,
    S: {here: 0, you: 0, day: 1, season: 1, cond: [0, 0, 0, 0, 0, 0, 0, 0]},
    route: 'hail',
    net: 'ok',
    h: (s) => String(s ?? ''),
    nm: (i) => ['You', 'Kim', 'Jai', 'A', 'B', 'C', 'D', 'E'][i],
    ship: (i) => 'LV-' + (i + 1),
    portrait: () => '<pt>',
    shipTop() {},
    dock(html) { el('dock').innerHTML = html; },
    go(r) { c.route = r; c._went = r; },
    view() { if (c.route === 'hail' || c.route.startsWith('hail/')) c.hailScreen(); },
    home() {},
    crew() {},
    setScreen() {},
    pollV: async () => ({}),
    api: api || (async (path, body) => { calls.push([path, body]); return {ok: true}; }),
    document: {addEventListener(type, fn) { if (type === 'click') listeners.push(fn); }},
    $: el,
    Date,
    setTimeout() { return 0; },
    clearTimeout() {},
    performance: {now: () => 0},
  });
  // live.js hooks view/home/setScreen/pollV and then defines hailScreen.
  vm.runInContext(source, c);
  const outgoing = live?.out || [{id: 'aabbcc', to: 1, ph: 1, t: 1, st: 0}];
  const state = {
    on: true, out: outgoing, in: [], peers: [{s: 1, ago: 10, cap: 1, off: 0, nl: 0}],
    max: 20, today: 1, light: true, lv: 1, me: 0,
    ...(live || {}),
  };
  // live.js binds LV with let; assign inside the context, not as a host property.
  c._lvstate = state;
  vm.runInContext('LV=_lvstate', c);
  return {
    c, calls, listeners, el,
    hail() { c.hailScreen(); return el('v').innerHTML + el('dock').innerHTML; },
    homeCard() { return vm.runInContext('lvHomeCard()', c); },
    status(o) { c._o = o; return vm.runInContext('lvSt(_o)', c); },
    async clickCancel(id, {disabled=false} = {}) {
      const btn = {disabled, dataset: {lvcx: id}};
      for (const fn of listeners) await fn({target: {closest: (s) => s.includes('data-lvcx') ? btn : null}});
    },
  };
}

test('hail menu shows Cancel hail for a hail on its way', () => {
  const p = phone();
  const html = p.hail();
  assert.match(html, /On its way/);
  assert.match(html, /you can take it back/);
  assert.match(html, /data-lvcx="aabbcc"/);
  assert.match(html, />Cancel hail</);
  assert.match(html, /Sending/);
});

test('hail menu has no cancel row when nothing is pending', () => {
  const p = phone({live: {out: [{id: 'x', to: 1, ph: 1, t: 1, st: 5}]}});
  const html = p.hail();
  assert.doesNotMatch(html, /On its way/);
  assert.doesNotMatch(html, /data-lvcx=/);
});

test('home card offers Cancel hail only while it can still be taken back', () => {
  const p = phone({live: {out: [
    {id: 'a1', to: 1, ph: 0, t: 1, st: 0},
    {id: 'a2', to: 2, ph: 1, t: 1, st: 2},
    {id: 'a3', to: 3, ph: 2, t: 1, st: 3},
    {id: 'a4', to: 4, ph: 3, t: 1, st: 5},
  ]}});
  const html = p.homeCard();
  assert.match(html, /data-lvcx="a1"/);
  assert.match(html, /data-lvcx="a2"/);
  assert.doesNotMatch(html, /data-lvcx="a3"/);
  assert.doesNotMatch(html, /data-lvcx="a4"/);
  assert.match(html, /You cancelled it/);
});

test('status words include You cancelled it', () => {
  const p = phone();
  assert.equal(p.status({st: 5, to: 1}), 'You cancelled it');
  assert.equal(p.status({st: 0, to: 1}), 'Sending…');
});

test('tapping Cancel hail posts /api/live/cancel once and disables the button', async () => {
  let posts = 0;
  const p = phone({
    api: async (path, body) => {
      if (path !== '/api/live/cancel') return {ok: true, out: p.c._lvstate.out, in: [], peers: p.c._lvstate.peers, on: true, max: 20, today: 1, lv: 1, me: 0};
      posts += 1;
      p.c._lvstate.out = [{id: 'aabbcc', to: 1, ph: 1, t: 1, st: 5}];
      vm.runInContext('LV=_lvstate', p.c);
      return {ok: true};
    },
  });
  p.hail();
  await p.clickCancel('aabbcc');
  assert.equal(posts, 1);
  const html = p.hail();
  assert.doesNotMatch(html, /data-lvcx=/);
  assert.match(p.homeCard(), /You cancelled it/);
});

test('a repeated tap while the first cancel is in flight is ignored', async () => {
  let resolve, posts = 0;
  const pending = new Promise((r) => { resolve = r; });
  const p = phone({
    api: async (path, body) => {
      if (path !== '/api/live/cancel') return {ok: true, out: p.c._lvstate.out, in: [], peers: p.c._lvstate.peers, on: true, max: 20, today: 1, lv: 1, me: 0};
      posts += 1;
      await pending;
      p.c._lvstate.out = [{id: 'aabbcc', to: 1, ph: 1, t: 1, st: 5}];
      vm.runInContext('LV=_lvstate', p.c);
      return {ok: true};
    },
  });
  p.hail();
  const first = p.clickCancel('aabbcc');
  const html = p.hail();
  assert.match(html, /disabled/);
  assert.match(html, /Taking it back/);
  // The real click handler ignores a disabled button (t.disabled).
  await p.clickCancel('aabbcc', {disabled: true});
  resolve();
  await first;
  assert.equal(posts, 1);
});

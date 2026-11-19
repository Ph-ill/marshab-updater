// Test-light timing without a browser, wall-clock waits or a ship.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./settings.js', import.meta.url), 'utf8');
function phone(api) {
  const listeners = [], timers = new Map();
  let next = 0;
  const c = vm.createContext({
    Date: class extends Date { static now() { return 100000; } },
    setTimeout(fn, ms) { timers.set(++next, { fn, ms }); return next; },
    clearTimeout(id) { timers.delete(id); },
    document: { addEventListener(type, fn) { if (type === 'click') listeners.push(fn); } },
    $: () => null, S: { led: false, here: 0 }, h: String, tok: 'test-token', api,
    shipTop() {}, view() {},
  });
  vm.runInContext(source, c);
  return {
    timers,
    html: () => vm.runInContext('ledtHTML(1)', c),
    async click() {
      const el = { disabled: false };
      for (const fn of listeners) await fn({ target: { closest: (s) => s === 'button[data-ledt]' ? el : null } });
    },
  };
}
for (const [label, reply, ms] of [
  ['ship says 10 s', { ms: 10000 }, 10000],
  ['duration comes from the API, not a hard-coded timer', { ms: 6500 }, 6500],
  ['missing duration falls back to 10 s', {}, 10000],
  ['null duration falls back to 10 s', { ms: null }, 10000],
]) {
  test(label, async () => {
    const p = phone(async () => reply);
    await p.click();
    assert.match(p.html(), new RegExp(`animation-duration:${ms}ms`));
    assert.match(p.html(), /disabled aria-busy=true/);
    assert.equal(p.timers.size, 1);
    const [timer] = p.timers.values();
    assert.equal(timer.ms, ms + 250);
    timer.fn();
    assert.doesNotMatch(p.html(), /aria-busy|ledbar/);
    assert.match(p.html(), /Finished\. The light is back to off\./);
  });
}
for (const ms of [7200, 0]) {
  test(`429 uses the remaining ${ms} ms, including zero, without the fallback`, async () => {
    const p = phone(async () => { throw { status: 429, j: { ms } }; });
    await p.click();
    assert.equal(p.timers.size, 1);
    assert.equal([...p.timers.values()][0].ms, ms + 250);
    if (ms) assert.match(p.html(), /animation-duration:7200ms/);
    else assert.doesNotMatch(p.html(), /aria-busy|ledbar/);
  });
}

test('another tap during a test does not call the API or restart its timer', async () => {
  let calls = 0;
  const p = phone(async () => { calls++; return { ms: 10000 }; });
  await p.click();
  const [id] = p.timers.keys();
  await p.click();
  assert.equal(calls, 1);
  assert.deepEqual([...p.timers.keys()], [id]);
});
test('429 during a hail says the light is showing a hail, not "three blinks" (review 3 m2)', async () => {
  const p = phone(async () => { throw { status: 429, j: { ms: 28400, kind: 'hail' } }; });
  await p.click();
  assert.match(p.html(), /Your ship's light is showing a hail\. Try again in 29 s\./);
  assert.doesNotMatch(p.html(), /aria-busy|ledbar|three blinks, then/);
  assert.equal(p.timers.size, 1);
  const [timer] = p.timers.values();
  assert.equal(timer.ms, 28400 + 250);
  timer.fn();
  assert.doesNotMatch(p.html(), /showing a hail/);
});

test('rgb ship uses the 18 s duration and says so once the ship has answered', async () => {
  const p = phone(async () => ({ ms: 18000, rgb: true }));
  await p.click();
  assert.match(p.html(), /animation-duration:18000ms/);
  assert.match(p.html(), /colours fading into each other, then back to red/);
  assert.equal([...p.timers.values()][0].ms, 18000 + 250);
  [...p.timers.values()][0].fn();
  assert.match(p.html(), />18 s</);
  assert.match(p.html(), /Finished\. The coloured lights are off again\./);
  assert.doesNotMatch(p.html(), />10 s</);
});

function resetPhone(api) {
  const listeners = {};
  const els = {};
  let html = "";
  const buttons = new Map();
  const c = vm.createContext({
    Date: class {
      getFullYear() { return 2026; }
      getMonth() { return 10; }
      getDate() { return 19; }
    },
    pad: (n) => String(n).padStart(2, "0"),
    S: { here: 4, led: null, you: 0, bat: null },
    h: String,
    nm: () => "Ada",
    tok: "test-token",
    api,
    view() {},
    shipTop() {},
    OI: false,
    OH: false,
    otaSect: () => "",
    otaNag: () => false,
    a2Kind: () => "",
    a2Std: () => false,
    chgSect: () => "",
    ledtHTML: () => "",
    batFacts: () => "",
    dock() {},
    bar() {},
    history: { replaceState() {} },
    location: { pathname: "/", search: "", reload() {} },
    route: "set",
    net: "live",
    me: 0,
    ws: null,
    poll: 0,
    fetch: async () => ({ ok: true }),
    localStorage: { clear() {} },
    sessionStorage: { clear() {} },
    setTimeout(fn, ms) { return 0; },
    clearInterval() {},
    Event: class { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } },
    document: {
      addEventListener(type, fn) { (listeners[type] ??= []).push(fn); },
      querySelector(sel) { return buttons.get(sel) || null; },
    },
    $: (id) => {
      if (id === "v") return { get innerHTML() { return html; }, set innerHTML(v) { html = v; }, insertAdjacentHTML() {} };
      if (id === "top") return null;
      if (!els[id]) els[id] = { value: "", checked: true, disabled: false, focus() {}, dispatchEvent() {} };
      return els[id];
    },
  });
  vm.runInContext(source, c);
  function render() { vm.runInContext("setScreen()", c); return html; }
  async function click(rst, el) {
    const target = el || {
      disabled: false,
      dataset: { rst },
      closest: (s) => s === "button[data-rst]" ? target : null,
      querySelector: () => ({ textContent: "" }),
    };
    if (el && !el.closest) target.closest = (s) => s === "button[data-rst]" ? el : null;
    for (const fn of listeners.click || []) await fn({ target });
  }
  return {
    c, els, listeners, render, click, html: () => html,
    el: (id) => vm.runInContext("$(" + JSON.stringify(id) + ")", c),
  };
}

test("reset confirm shows start-from-today on by default, second person, no spoiler numbers", () => {
  const p = resetPhone(async () => ({ ok: true, restart_ms: 1500 }));
  vm.runInContext('RST="ask";RSTF=true', p.c);
  const html = p.render();
  assert.match(html, /id=rstf checked/);
  assert.match(html, /Start the voyage again from today/);
  assert.match(html, /You'll be on day 1 after the restart/);
  assert.match(html, /Leave this off to clear progress but keep the original start date/);
  assert.match(html, /Ships in range may sync their records back/);
  assert.doesNotMatch(html, /launch_date|clock\.json|duel\.json|from_today/);
});

test("reset body sends this phone's local date when the box is checked, only confirm when not", () => {
  const p = resetPhone(async () => ({ ok: true }));
  const on = JSON.parse(vm.runInContext("RSTF=true;JSON.stringify(rstBody(5))", p.c));
  const off = JSON.parse(vm.runInContext("RSTF=false;JSON.stringify(rstBody(5))", p.c));
  assert.deepEqual(on, { confirm: 5, from_today: true, date: "2026-11-19" });
  assert.deepEqual(off, { confirm: 5 });
});

test("Reset this ship opens the confirm with the box checked again", async () => {
  const p = resetPhone(async () => ({ ok: true }));
  vm.runInContext("RSTF=false;RST=null", p.c);
  await p.click("ask");
  assert.equal(vm.runInContext("RST", p.c), "ask");
  assert.equal(vm.runInContext("RSTF", p.c), true);
  assert.match(p.html(), /id=rstf checked/);
});

test("unchecking the box is kept if the ship refuses, and the post omitted from_today", async () => {
  const calls = [];
  const p = resetPhone(async (path, body) => {
    calls.push({ path, body });
    throw { message: "The ship needs a date and the time from your phone to start today." };
  });
  vm.runInContext('RST="ask";RSTF=true', p.c);
  p.render();
  p.el("rstn").value = "5";
  vm.runInContext("RSTF=false", p.c);
  p.el("rstf").checked = false;
  await p.click("go");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ path: "/api/reset", body: { confirm: 5 } }]);
  assert.equal(vm.runInContext("RSTF", p.c), false);
  assert.match(p.html(), /Start the voyage again from today/);
  assert.doesNotMatch(p.html(), /id=rstf checked/);
});

test("a successful reset with the box on posts from_today and today's date", async () => {
  const calls = [];
  const p = resetPhone(async (path, body) => {
    calls.push({ path, body });
    return { ok: true, restart_ms: 1500 };
  });
  vm.runInContext('RST="ask";RSTF=true', p.c);
  p.render();
  p.el("rstn").value = "5";
  await p.click("go");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{
    path: "/api/reset",
    body: { confirm: 5, from_today: true, date: "2026-11-19" },
  }]);
});


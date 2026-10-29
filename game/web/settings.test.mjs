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
    $: () => null, S: { led: false }, h: String, tok: 'test-token', api,
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

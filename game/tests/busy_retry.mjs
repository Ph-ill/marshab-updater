// The ship's admission refusal (503 + Retry-After: 1, board/main.py ota_route) is "busy, ask
// again", never a miss (0.3.0 review 3 m3). Two raw-fetch callers that api() doesn't cover:
//   web/funnel.js fnHello  (/api/hello): a busy answer must not become "never seen" (ADD)
//   web/live.js lvTest     (radio test pings): a busy answer must not count as missed
// Each function is taken from the page source as written and run with a scripted fetch.
//   node tests/busy_retry.mjs           (from game/)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const fails = [];
const check = (ok, msg) => { if (!ok) { fails.push(msg); console.log('FAIL', msg); } };
const take = (file, name) => {
  const src = readFileSync(file, 'utf8');
  const i = src.indexOf(`async function ${name}(`);
  if (i < 0) throw new Error(`${name} not found in ${file}`);
  const j = src.indexOf('\n}\n', i);
  return src.slice(i, j + 2);
};
const answer = (status, body, hdr = {}) => new Response(body, { status, headers: hdr });
const busy = () => answer(503, '{"err":"busy, try again"}', { 'Retry-After': '1' });

// funnel: two busy answers, then the ship's record
{
  const seq = [busy(), busy(), answer(200, '{"installed":true}')];
  const asked = [];
  const ctx = vm.createContext({ FN: { k: 'ios' }, AbortController, setTimeout, clearTimeout, Date, Promise, URLSearchParams,
    fetch: async (u) => { asked.push(u); return seq.shift() || answer(500, '{}'); } });
  ctx.window = ctx;
  vm.runInContext(take('web/funnel.js', 'fnHello'), ctx);
  const r = await vm.runInContext('fnHello(false)', ctx);
  check(r && r.installed === true, 'fnHello: busy twice, then the record (not null/ADD): ' + JSON.stringify(r));
  check(asked.length === 3, 'fnHello asked 3 times: ' + asked.length);
  // a real failure is still unknown (null), with no retry
  const seq2 = [answer(500, '{}')];
  ctx.fetch = async () => seq2.shift();
  check((await vm.runInContext('fnHello(false)', ctx)) === null, 'fnHello: a 500 is still unknown');
}

// radio test: busy answers are asked again, not counted as missed
{
  let n = 0;
  const ctx = vm.createContext({ LV_TN: 4, LVR: null, LVC: null, route: 'coex', tok: 't', performance, setTimeout, Promise, Math,
    view() {}, go() {}, api: async () => ({}),
    fetch: async (u) => { n++; if (n === 2 || n === 3) return busy();
      const kb = +new URL(u, 'http://x').searchParams.get('kb'); return answer(200, ' '.repeat(kb * 1024), { 'X-Ble': 'idle' }); } });
  vm.runInContext('var LV_TN=4,LVR=null,LVC=null;' + take('web/live.js', 'lvTest'), ctx);
  await vm.runInContext('lvTest()', ctx);
  const p = vm.runInContext('LVR.p', ctx);
  check(p.length === 4 && p.every((x) => x.ok), 'radio test: 4 answers, none missed: ' + JSON.stringify(p));
  check(n === 6, 'radio test: the 2 busy answers were asked again: ' + n);
}
console.log(`busy retry (funnel hello, radio test): ${fails.length ? 'FAIL' : 'ok'}`);
process.exit(fails.length ? 1 : 0);

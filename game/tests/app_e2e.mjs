// End to end: the real phone page (build/app.html.gz, as the board serves it) in headless
// Chrome, against the board's own server code (board/lvweb.py + lvphone.py via
// tests/phone_serve.py) on CPython or the MicroPython unix port. Drives the app's own
// buttons: wrong code, sign in, story renders, vote (or answer), a gift, a drop opened,
// a crewmate's tap reaching this phone by polling (the board has no WebSocket), sign out.
// Fails on page exceptions, console errors and unexpected HTTP errors.
//   node --experimental-websocket tests/app_e2e.mjs [day]          (from game/)
//   BOARD_PY="/path/to/micropython -X heapsize=1m" ... runs the server on MicroPython
//   CHROME=/usr/bin/google-chrome (default)
import { spawn } from 'node:child_process';
const DAY = +(process.argv[2] || 9), PORT = 8180 + (process.pid % 50), CDP = 9400 + (process.pid % 50);
const BASE = `http://127.0.0.1:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [];
const step = (s) => { if (process.env.E2E_DEBUG) console.log('..', s); };
const check = (ok, msg) => { if (!ok) { fails.push(msg); console.log('FAIL', msg); } };
const [py, ...pyArgs] = (process.env.BOARD_PY || 'python3').split(' ');
const board = spawn(py, [...pyArgs, 'tests/phone_serve.py', String(DAY), String(PORT)], { stdio: ['ignore', 'pipe', 'inherit'] });
let crew = -1;
await new Promise((res, rej) => {
  let buf = '';
  board.stdout.on('data', (d) => { buf += d; const m = buf.match(/CREW (\d+)/); if (m) crew = +m[1]; if (/READY/.test(buf)) res(); });
  board.on('exit', (c) => rej(new Error('board server exited ' + c)));
  setTimeout(() => rej(new Error('board server did not start')), 60000).unref();
});
const chrome = spawn(process.env.CHROME || 'google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${CDP}`,
  `--user-data-dir=${process.env.TMPDIR || '/tmp'}/lv-app-e2e-${process.pid}`, 'about:blank'], { stdio: 'ignore' });
const done = (code) => { try { chrome.kill(); } catch {} try { board.kill(); } catch {} process.exit(code); };
try {
  let ws;
  for (let i = 0; i < 60 && !ws; i++) { try { const l = await (await fetch(`http://127.0.0.1:${CDP}/json`)).json(); const p = l.find((t) => t.type === 'page'); if (p) ws = p.webSocketDebuggerUrl; } catch {} await sleep(200); }
  const sock = new WebSocket(ws); await new Promise((r) => (sock.onopen = r));
  let id = 0, wsTried = false; const pending = new Map(); const problems = []; const http = [];
  sock.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') problems.push('console: ' + m.params.args.map((a) => a.value ?? a.description).join(' '));
    if (m.method === 'Runtime.exceptionThrown') problems.push('exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === 'Network.webSocketCreated' && m.params.url.endsWith('/ws')) wsTried = true;
    if (m.method === 'Network.responseReceived') http.push([m.params.response.status, new URL(m.params.response.url).pathname]);
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); sock.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result; if (r.exceptionDetails) throw new Error(expr.slice(0, 60) + ': ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text)); return r.result.value; };
  const until = async (expr, ms = 8000, what = expr) => { for (let t = 0; t < ms; t += 100) { if (await ev(expr)) return true; await sleep(100); } check(false, 'timed out: ' + what); return false; };
  const click = (sel) => ev(`(()=>{const b=document.querySelector(${JSON.stringify(sel)});if(!b)return false;b.click();return true})()`);
  await send('Runtime.enable'); await send('Network.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await send('Network.setUserAgentOverride', { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 e2e' });
  step('navigate');
  await send('Page.navigate', { url: BASE + '/' });
  await until(`document.querySelectorAll('[data-who]').length===8`, 15000, 'the crew list');
  const C = crew;
  step('crew list');
  // A wrong code first: the ship counts down.
  check(await click(`[data-who="${C}"]`), 'crew button');
  for (const k of '0000') await click(`[data-key="${k}"]`);
  await until(`(document.querySelector('.err')||{}).textContent?.includes('4 tries')`, 8000, 'wrong code: 4 tries left');
  step('code 1234');
  for (const k of '1234') await click(`[data-key="${k}"]`);
  await until(`typeof S==='object'&&S!==null&&S.you===${C}`, 15000, 'signed in, state loaded');
  if (await ev(`!!document.querySelector('.big')`)) await click('[data-go="home"]');
  step('state');
  const st = JSON.parse(await ev(`JSON.stringify({day:S.day,season:S.season,here:S.here,v:S.v,story:S.story.length,open:S.open.map(o=>[o.card,o.type,o.mine]),lines:story().length||Object.keys(story()).length})`));
  check(st.day === DAY && st.here === 2 && st.story > 0 && st.story % 4 === 0, 'state: ' + JSON.stringify(st));
  check(st.lines > 0, 'story rendered no lines');
  // Vote on (or answer) the first open card through its screen.
  const card = st.open.find((o) => (o[1] === 3 || o[1] === 4) && o[2] == null);
  let voted = null;
  if (card) {
    await ev(`go("item/${card[0]}")`);
    await until(`!!document.querySelector('[data-pick^="${card[0]}:"]')`, 4000, 'vote options');
    await click(`[data-pick^="${card[0]}:"]`);
    await until(`!!document.querySelector('[data-send="${card[0]}"]')&&!document.querySelector('[data-send="${card[0]}"]').disabled`, 4000, 'send button');
    await click(`[data-send="${card[0]}"]`);
    await until(`S.open.some(o=>o.card===${card[0]}&&o.mine!=null)`, 8000, 'vote recorded in the state');
    voted = card;
  }
  step('gift');
  // A gift through the gifts screen: mode, a crewmate, the first item it offers, send.
  await ev(`go("gifts")`);
  await until(`!!document.querySelector('[data-eng^="to:"]')`, 4000, 'gift recipients');
  await click('[data-eng="mode:0"]');
  await click('[data-eng^="to:"]');
  await until(`!!document.querySelector('[data-eng^="item:"]:not([disabled])')`, 4000, 'giftable items');
  const v0 = await ev('S.v');
  await click('[data-eng^="item:"]:not([disabled])');
  await until(`!!document.querySelector('[data-eng="send"]:not([disabled])')`, 4000, 'gift send button');
  await click('[data-eng="send"]');
  await until(`S.v!==${v0}&&!document.querySelector('[role=alert]')`, 8000, 'gift accepted');
  step('drop');
  // Today's drop, if it is still sealed.
  const drop = await ev(`(()=>{const b=document.querySelector('[data-go^="drop/"]');return b?b.dataset.go:null})()`);
  if (drop) {
    await ev(`go(${JSON.stringify(drop)})`);
    if (await click('[data-eng^="open:"]')) await until(`location.hash.includes('drop')||route.startsWith('drop')`, 4000, 'drop opened');
  }
  step('poll');
  // A crewmate on another phone taps; this phone sees it by polling /api/v (no WebSocket on the board).
  const other = (C + 1) % 7 === 5 ? (C + 2) % 7 : (C + 1) % 7;
  const H = { 'User-Agent': 'other-phone', 'Content-Type': 'application/json' };
  const lg = await (await fetch(BASE + '/api/login', { method: 'POST', headers: H, body: JSON.stringify({ crew: other, pin: '1234' }) })).json();
  const vb = await ev('S.v');
  const r = await fetch(BASE + '/api/act', { method: 'POST', headers: { ...H, 'X-Crew-Token': lg.token }, body: JSON.stringify({ act: 0, param: 0, tgt: 0 }) });
  check(r.status === 200, 'other phone act: ' + r.status);
  check(await ev('net') === 'poll', 'no WebSocket on the board: the page should be polling');
  await until(`S.v!==${vb}`, 20000, 'the poll picked up a crewmate\'s tap');
  step('sign out');
  // Sign out, from the crew page (your astronaut).
  await ev(`go("crew")`);
  await until(`!!document.querySelector('[data-out]')`, 4000, 'crew page with the sign-out button');
  const crewRows = await ev(`document.querySelectorAll('[data-go^="crew/"]').length`);
  check(crewRows === 7, 'crew page lists ' + crewRows + ' crewmates');
  await click('[data-out]');
  await until(`tok===""&&document.querySelectorAll('[data-who]').length===8`, 4000, 'signed out');
  // HTTP: only the expected errors (the wrong code's 403, the WebSocket's 404).
  // (and /api/me's 401 when the page opens signed out).
  const bad = http.filter(([s, p], i) => s >= 400 && !(s === 403 && p === '/api/login') && !(s === 401 && p === '/api/me'));
  check(bad.length === 0, 'HTTP errors: ' + JSON.stringify(bad));
  check(wsTried, 'the page tried the WebSocket and fell back to polling');
  check(problems.length === 0, 'page problems: ' + JSON.stringify(problems));
  console.log(`app e2e on ${py.split('/').pop()}, day ${DAY}, crew ${C}: ${http.length} requests, ` +
    `${voted ? 'voted card ' + voted[0] : 'nothing to vote on'}, gift sent${drop ? ', drop ' + drop : ''}, poll saw a crewmate, signed out: ${fails.length ? 'FAIL' : 'ok'}`);
  sock.close();
  done(fails.length ? 1 : 0);
} catch (e) { console.log('FAIL', e.message); done(1); }

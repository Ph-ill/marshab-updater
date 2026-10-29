// End to end (0.3.0 review 2 M1): a ship whose first phone had a wrong clock, and the
// pre-launch countdown that clock started. The real phone page (build/app.html.gz) in
// headless Chrome against the board's server code (tests/phone_serve.py, with main.py's
// clock gate and over-the-air hooks as they are).
//   1. The ship learned its time from a phone set to the day before launch, so it shows the
//      countdown. Once a ship knows its time, only a signed-in phone can move it.
//   2. This phone (also before launch at first) can still sign in on the countdown. It gets
//      the countdown with the gear, and Settings opens with Ship software (the ship's
//      answer to /api/ota, Check for updates), the Ship light and Sign out.
//   3. This phone's clock is then set right (flight day 2). The page's own 30 s check,
//      signed in, moves the ship to the right day. The page leaves the countdown for FD 02,
//      the crew briefing is still due (the countdown sign-in didn't spend it: review 2 m2),
//      and Settings with Ship software is still there.
// Fails on page exceptions, console errors and unexpected HTTP errors.
//   node --experimental-websocket tests/app_clock_e2e.mjs          (from game/)
//   BOARD_PY="/path/to/micropython -X heapsize=1m" ... runs the server on MicroPython
import { spawn } from 'node:child_process';
const PORT = 8240 + (process.pid % 50), CDP = 9460 + (process.pid % 50);
const BASE = `http://127.0.0.1:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [];
const check = (ok, msg) => { if (!ok) { fails.push(msg); console.log('FAIL', msg); } };
const [py, ...pyArgs] = (process.env.BOARD_PY || 'python3').split(' ');
// Launch 2026-11-08 (CST, UTC-6). The first phone said 2026-11-07 12:00, so the ship counts down.
// The real time is 2026-11-10 05:50: before 06:00 that is still the day that began on the 9th, FD 2.
const LAUNCH = '2026-11-08', TZ = -360;
const WRONG = Date.UTC(2026, 10, 7, 18, 0), REAL = Date.UTC(2026, 10, 10, 11, 50);
const board = spawn(py, [...pyArgs, 'tests/phone_serve.py', '0', String(PORT), LAUNCH, String(WRONG), String(TZ)], { stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise((res, rej) => {
  let buf = '';
  board.stdout.on('data', (d) => { buf += d; if (/READY/.test(buf)) res(); });
  board.on('exit', (c) => rej(new Error('board server exited ' + c)));
  setTimeout(() => rej(new Error('board server did not start')), 60000).unref();
});
const chrome = spawn(process.env.CHROME || 'google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${CDP}`,
  `--user-data-dir=${process.env.TMPDIR || '/tmp'}/lv-clock-e2e-${process.pid}`, 'about:blank'], { stdio: 'ignore' });
const done = (code) => { try { chrome.kill(); } catch {} try { board.kill(); } catch {} process.exit(code); };
try {
  let ws;
  for (let i = 0; i < 60 && !ws; i++) { try { const l = await (await fetch(`http://127.0.0.1:${CDP}/json`)).json(); const p = l.find((t) => t.type === 'page'); if (p) ws = p.webSocketDebuggerUrl; } catch {} await sleep(200); }
  const sock = new WebSocket(ws); await new Promise((r) => (sock.onopen = r));
  let id = 0; const pending = new Map(); const problems = []; const http = [];
  sock.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') problems.push('console: ' + m.params.args.map((a) => a.value ?? a.description).join(' '));
    if (m.method === 'Runtime.exceptionThrown') problems.push('exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === 'Network.responseReceived') http.push([m.params.response.status, new URL(m.params.response.url).pathname]);
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); sock.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result; if (r.exceptionDetails) throw new Error(expr.slice(0, 60) + ': ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text)); return r.result.value; };
  const until = async (expr, ms = 8000, what = expr) => { for (let t = 0; t < ms; t += 100) { if (await ev(expr)) return true; await sleep(100); } check(false, 'timed out: ' + what); return false; };
  const click = (sel) => ev(`(()=>{const b=document.querySelector(${JSON.stringify(sel)});if(!b)return false;b.click();return true})()`);
  const day = async () => (await (await fetch(BASE + '/api/crew')).json()).day;
  await send('Runtime.enable'); await send('Network.enable'); await send('Page.enable');
  // This phone's clock starts as wrong as the first phone's (a few minutes later); __shift moves it.
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(()=>{const r=Date.now.bind(Date);let o=${WRONG + 300000}-r();Date.now=()=>r()+o;` +
    `Date.prototype.getTimezoneOffset=function(){return ${-TZ}};window.__shift=(m)=>{o+=m}})()` });
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  // Opened from the icon (no home-screen guide in the way)
  await send('Network.setUserAgentOverride', { userAgent: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36 e2e' });
  await send('Page.navigate', { url: BASE + '/?src=icon' });
  check(await day() === 0, 'the ship counts down after a wrong first clock');
  // 1. The countdown, with the crew list to sign in on
  await until(`typeof PRE==='object'&&PRE!==null&&document.querySelectorAll('[data-who]').length===8`, 15000, 'countdown with the crew list');
  check(/Crew can sign in now for Settings/.test(await ev(`document.querySelector('.kick.pre')?.textContent||''`)), 'countdown says crew can sign in');
  check(await ev(`![...document.querySelectorAll('[data-who]')].some((b)=>b.disabled)`), 'names not disabled in the countdown');
  // 2. Sign in during the countdown: the countdown with the gear; Settings and Ship software
  check(await click('[data-who="2"]'), 'crew button in the countdown');
  for (const k of '1234') await click(`[data-key="${k}"]`);
  await until(`!!tok&&typeof S==='object'&&S!==null&&S.pre&&S.you===2`, 15000, 'signed in during the countdown');
  check(await ev(`!!document.querySelector('.kick.pre')&&/signed in/.test(document.querySelector('#v').textContent)`), 'signed-in countdown screen');
  check(await ev(`(b=>!!b&&b.getAttribute("aria-label")==="Settings")(document.querySelector('#top .gear'))`), 'gear in the top bar in the countdown');
  check(await day() === 0, 'a signed-in phone with the same (wrong) date leaves the day alone');
  await click('#top .gear');
  await until(`route==="set"&&!!document.querySelector('#set-sw')&&!!document.querySelector('#set-out')`, 6000, 'Settings open in the countdown');
  await until(`!!document.querySelector('#set-sw [data-ota=check]')`, 15000, 'Ship software: the ship said what it runs (countdown)');
  check(!/USB/.test(await ev(`document.querySelector('#set-sw').textContent`)), 'Ship software in the countdown: no USB message');
  check(http.some(([s, p]) => s === 200 && p === '/api/ota'), 'the page asked the ship what it runs (/api/ota 200)');
  check(http.some(([s, p]) => s === 409 && p === '/api/state'), 'the countdown state (409 with what Settings needs)');
  await ev(`go("home")`);
  await until(`!!document.querySelector('.kick.pre')`, 4000, 'back to the countdown');
  // 3. This phone's clock set right: its next check moves the ship to flight day 2
  await ev(`__shift(${REAL - WRONG})`);
  await until(`S&&!S.pre&&S.day===2&&!!S.story`, 45000, 'flight day 2 after the clock is corrected');
  check(await day() === 2, 'the ship is on flight day 2');
  check(await ev(`PRE===null&&!document.querySelector('.kick.pre')`), 'the countdown is gone');
  check(await ev(`tutDue&&route==='meet'&&!!document.querySelector('[data-go="how"]')`), 'the crew briefing is still due on flight day 2 (not spent in the countdown)');
  await ev(`go("home")`);
  await until(`route==='home'&&document.querySelector('#top').textContent.includes('FD 02')`, 6000, 'home on FD 02');
  await click('#top .gear');
  await until(`route==="set"&&!!document.querySelector('#set-sw [data-ota=check]')`, 15000, 'Settings and Ship software on flight day 2');
  check(!/USB/.test(await ev(`document.querySelector('#set-sw').textContent`)), 'Ship software on flight day 2: no USB message');
  const bad = http.filter(([s, p]) => s >= 400 && !(s === 409 && (p === '/api/state' || p === '/api/v')) && !(s === 401 && p === '/api/me'));
  check(bad.length === 0, 'unexpected HTTP errors: ' + JSON.stringify(bad));
  check(problems.length === 0, 'page problems: ' + JSON.stringify(problems));
  console.log(`app clock e2e on ${py.split('/').pop()}: ${http.length} requests, wrong first clock -> countdown sign-in, Settings + Ship software -> FD 02: ${fails.length ? 'FAIL' : 'ok'}`);
  sock.close();
  done(fails.length ? 1 : 0);
} catch (e) { console.log('FAIL', e.message); done(1); }

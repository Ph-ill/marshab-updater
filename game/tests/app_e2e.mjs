// End to end: the real phone page (build/app.html.gz, as the board serves it) in headless
// Chrome, against the board's own server code (board/lvweb.py + lvphone.py via
// tests/phone_serve.py) on CPython or the MicroPython unix port. Drives the app's own
// buttons: the eight portraits on the sign-in list, wrong code, sign in, the crew briefing a
// first sign-in shows (every card, then Go aboard), story renders, vote (or answer), a gift,
// a drop opened, a crewmate's tap reaching this phone by polling (the board has no
// WebSocket), sign out, and a second sign-in that skips the briefing.
// The ship runs on the calendar (board/lvcal.py): launch date DAY days before a phone date in
// November at 05:50 CST, so it's flight day DAY; then the phone's clock jumps past 06:00 and
// the page must show DAY+1 by its next poll. Last, the pre-launch countdown screen.
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
// The phone's clock: 2026-11-10 05:50 CST (UTC-6) ...; before 06:00 it is still the day that began 06:00 on the 9th, so FD 1 = 2026-11-(10-DAY).
const T0 = Date.UTC(2026, 10, 10, 11, 50), TZ = -360;
const LAUNCH = new Date(Date.UTC(2026, 10, 10 - DAY)).toISOString().slice(0, 10);
const board = spawn(py, [...pyArgs, 'tests/phone_serve.py', String(DAY), String(PORT), LAUNCH, String(T0), String(TZ)], { stdio: ['ignore', 'pipe', 'inherit'] });
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
  // This phone's clock and zone, as the page reads them (Date.now, getTimezoneOffset); __shift(ms) moves it.
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(()=>{const r=Date.now.bind(Date);let o=${T0}-r();Date.now=()=>r()+o;` +
    `Date.prototype.getTimezoneOffset=function(){return ${-TZ}};window.__shift=(m)=>{o+=m}})()` });
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await send('Network.setUserAgentOverride', { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 e2e' });
  step('navigate');
  await send('Page.navigate', { url: BASE + '/' });
  await until(`document.querySelectorAll('[data-who]').length===8`, 15000, 'the crew list');
  const C = crew;
  step('portraits');
  // The portraits: eight on the sign-in list, eight distinct helmet shells, each crew entry
  // just [visor, helmet detail] (no chest symbols), Phill's flagship crest in portrait 0.
  const pt = JSON.parse(await ev(`JSON.stringify({svgs:document.querySelectorAll('[data-who] svg').length,hel:HEL.length,
    shells:new Set(HEL.map(x=>x[0])).size,pics:new Set([0,1,2,3,4,5,6,7].map(i=>portrait(i))).size,
    entries:CREW.every(x=>x.length===2),crest:portrait(0).includes('M29.6 10.3L31 3.5H33')})`));
  check(pt.svgs === 8 && pt.hel === 8 && pt.shells === 8 && pt.pics === 8, 'portraits: ' + JSON.stringify(pt));
  check(pt.entries, 'crew portrait entries carry more than visor and helmet detail (a chest symbol?)');
  check(pt.crest, "Phill's flagship crest is missing from portrait 0");
  step('crew list');
  // A wrong code first: the ship counts down.
  check(await click(`[data-who="${C}"]`), 'crew button');
  for (const k of '0000') await click(`[data-key="${k}"]`);
  await until(`(document.querySelector('.err')||{}).textContent?.includes('4 tries')`, 8000, 'wrong code: 4 tries left');
  step('code 1234');
  for (const k of '1234') await click(`[data-key="${k}"]`);
  await until(`typeof S==='object'&&S!==null&&S.you===${C}`, 15000, 'signed in, state loaded');
  step('briefing');
  // A first sign-in: the ship says `first`, so the meet screen offers the crew briefing
  // instead of Go aboard. Every card, then Go aboard lands on Home and the phone remembers.
  await until(`route==='meet'&&tutDue&&!!document.querySelector('.big')`, 8000, 'meet screen (briefing due) on the first sign-in');
  check(/10 cards/.test(await ev(`(document.querySelector('[data-go="how"]')||{}).textContent||''`)), 'meet screen: the briefing button gives the card count');
  check(await click('[data-go="how"]'), 'meet screen: no Crew briefing button on a first sign-in');
  await until(`!!document.querySelector('.tut')`, 4000, 'crew briefing card');
  const cards = await ev('TUT().length');
  check(cards === 10, 'briefing has ' + cards + ' cards (expected 10: 3 intro, then 7 with engagement and the ship light)');
  const leads = [await ev(`document.querySelector('.tut .lead').textContent`)];
  check(/Intro 01\/10/.test(await ev(`document.querySelector('.tut .lab').textContent`)), 'briefing card 1 is labelled Intro 01/10');
  let seen = 1;
  for (let i = 1; i < cards; i++) {
    await click('[data-tut=next]');
    if (await until(`!!document.querySelector('.tut')&&tutStep()===${i}`, 4000, 'briefing card ' + (i + 1))) seen++;
    leads.push(await ev(`document.querySelector('.tut .lead').textContent`));
  }
  check(/Mars/.test(leads[0]) && /Pico W/.test(leads[1]) && /LV-3\b/.test(leads[1]) && /No internet/.test(leads[1]),
    'intro cards: the goal, then the ship (Pico W, its Wi-Fi LV-3, no internet): ' + leads.slice(0, 2).join(' | '));
  check(/every morning at 6\b/.test(leads[2]) && /six weeks/.test(leads[2]), 'intro card 3 gives the day start and the length: ' + leads[2]);
  check(leads.some((l) => /Bluetooth/.test(l) && /in range/.test(l)), 'a card says how things travel by Bluetooth');
  check(leads.some((l) => /puls/.test(l)), 'a card explains the ship light');
  check(seen === cards, 'briefing cards seen ' + seen + '/' + cards);
  check(await click('[data-tut=done]'), 'last briefing card: no Go aboard button');
  await until(`route==='home'&&localStorage.getItem('lv-briefed')==='1'`, 4000, 'briefing done: home, remembered');
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
  if (DAY < 42) {
    step('06:00');
    // The phone's clock crosses 06:00: the ship moves to the next flight day and the page,
    // polling /api/v every 15 s, shows it (and the new day's story) without a reload.
    await ev('go("home")');
    await ev('__shift(12*60000)');
    await until(`S.day===${DAY + 1}&&document.querySelector('#top').textContent.includes('FD ${String(DAY + 1).padStart(2, '0')}')`, 45000, 'the next flight day after 06:00');
  }
  step('sign out');
  // Sign out, from the crew page (your astronaut).
  await ev(`go("crew")`);
  await until(`!!document.querySelector('[data-out]')`, 4000, 'crew page with the sign-out button');
  const crewRows = await ev(`document.querySelectorAll('[data-go^="crew/"]').length`);
  check(crewRows === 7, 'crew page lists ' + crewRows + ' crewmates');
  // Who's in Bluetooth range (S.air): a nearby ship gets the rust "Nearby" mark, the others
  // when they were last in range. The mock sends a fixed sample; a board without a radio null (nothing shown).
  const air = JSON.parse(await ev(`JSON.stringify({air:S.air,near:document.querySelectorAll('[data-go^="crew/"] .near').length,txt:[...document.querySelectorAll('[data-go^="crew/"] small')].map((x)=>x.textContent)})`));
  const nNear = (air.air || []).filter((x) => x[0] !== st.here && x[1] <= 180).length;
  check((air.air === null || Array.isArray(air.air)) && air.near === nNear && (!(air.air || []).length || air.txt.some((t) => /^In range \d+ (min|h) ago$/.test(t))),
    'crew page Bluetooth contact: ' + JSON.stringify(air));
  // The marks themselves, from a sample like a board with a radio sends (this server has none):
  // a ship heard 20 s ago is Nearby, one heard 15 min ago was in range then, the rest unheard.
  const mk = JSON.parse(await ev(`(S.air=[[(S.here+1)%8,20,false],[(S.here+2)%8,900,true]],crew(),JSON.stringify([...document.querySelectorAll('[data-go^="crew/"] small:nth-of-type(2)')].map((x)=>x.textContent)))`));
  // (no mark for this ship's own astronaut: their ship is this one)
  check(mk.length >= 5 && mk.filter((t) => t === 'Nearby · syncing').length === 1 &&
    mk.includes('In range 15 min ago') && mk.filter((t) => t === 'Not in range lately').length === mk.length - 2,
    'crew page Bluetooth marks from a sample: ' + JSON.stringify(mk));
  // The Ship light switch (the board's LED notifier): the board answers on (game firmware)
  // or stays off (a plain interpreter); the button shows what the board said. Back off after.
  check(await ev(`!!document.querySelector('[data-led]')`), 'Ship light button on your crew page');
  await click('[data-led]');
  await until(`typeof S.led==="boolean"&&!document.querySelector('[data-led]').disabled&&document.querySelector('[data-led]').textContent.includes("Ship light: "+(S.led?"on":"off"))`, 4000, 'Ship light answered');
  if (await ev('S.led')) {
    await click('[data-led]');
    await until(`S.led===false&&document.querySelector('[data-led]').textContent.includes("Ship light: off")`, 4000, 'Ship light off again');
  }
  await click('[data-out]');
  await until(`tok===""&&document.querySelectorAll('[data-who]').length===8`, 4000, 'signed out');
  step('second sign-in');
  // Signing in again: not first any more, and the phone remembers the briefing: straight Home.
  await click(`[data-who="${C}"]`);
  for (const k of '1234') await click(`[data-key="${k}"]`);
  await until(`tok!==""&&route==='home'&&!tutDue&&!document.querySelector('.tut')`, 15000, 'second sign-in goes straight Home');
  await ev(`go("crew")`);
  await until(`!!document.querySelector('[data-out]')`, 4000, 'sign-out button');
  await click('[data-out]');
  await until(`tok===""`, 4000, 'signed out again');
  step('pre-launch');
  // The countdown the page shows before launch ({day: 0, launch, until} from /api/crew): no sign-in.
  await ev(`(PRE={day:0,launch:"2026-11-12",until:125},hello(),1)`);
  const pre = JSON.parse(await ev(`JSON.stringify({h:document.querySelector('.pre h1').textContent,p:document.querySelector('.pre p').textContent,on:document.querySelectorAll('[data-who]:not([disabled])').length})`));
  check(pre.h === 'Launch in 2 h 5 min' && /starts at 06:00/.test(pre.p) && pre.on === 0, 'pre-launch screen: ' + JSON.stringify(pre));
  await ev('(PRE=null,hello(),1)');
  // HTTP: only the expected errors (the wrong code's 403, the WebSocket's 404).
  // (and /api/me's 401 when the page opens signed out).
  const bad = http.filter(([s, p], i) => s >= 400 && !(s === 403 && p === '/api/login') && !(s === 401 && p === '/api/me'));
  check(bad.length === 0, 'HTTP errors: ' + JSON.stringify(bad));
  check(http.some(([s, p]) => s === 200 && p === '/api/ota'), 'the page asked the ship about updates (web/ota.js)');
  check(wsTried, 'the page tried the WebSocket and fell back to polling');
  // The home screen (web/a2hs.js): the manifest and icon the page's <head> names, from the ship.
  const mf = await fetch(BASE + '/app.webmanifest'), ic = await fetch(BASE + '/icon.png');
  const mj = mf.status === 200 ? await mf.json() : {}, ib = Buffer.from(await ic.arrayBuffer());
  check(/manifest\+json/.test(mf.headers.get('content-type')) && mj.short_name === 'Long Voyage' && mj.start_url === '/' && mj.icons[0].src === '/icon.png', 'manifest: ' + mf.status + ' ' + JSON.stringify(mj));
  check(ic.status === 200 && ic.headers.get('content-type') === 'image/png' && ib.readUInt32BE(16) === 192 && ib.readUInt32BE(20) === 192, 'icon: ' + ic.status + ' ' + ib.length + ' B');
  const hd = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('head link[rel],head meta[name^=apple]')].map((e)=>e.rel||e.name+'='+e.content))`));
  // This browser says iPhone and has anchor positioning, so app.html takes it for iOS 26 and
  // leaves out the manifest and Apple's web-app tags (they give the icon a too-short window
  // there); web/shots_a2hs.mjs checks they're added on iOS 18, Android and computers.
  check(['icon', 'apple-touch-icon'].every((x) => hd.includes(x)) && !hd.includes('manifest') && !hd.some((x) => /^apple-mobile-web-app/.test(x)), 'home-screen tags (iOS 26): ' + JSON.stringify(hd));
  check(problems.length === 0, 'page problems: ' + JSON.stringify(problems));
  console.log(`app e2e on ${py.split('/').pop()}, day ${DAY}, crew ${C}: ${http.length} requests, ` +
    `${voted ? 'voted card ' + voted[0] : 'nothing to vote on'}, gift sent${drop ? ', drop ' + drop : ''}, poll saw a crewmate, briefing ${cards} cards, 8 portraits${DAY < 42 ? ', FD ' + DAY + ' -> ' + (DAY + 1) + ' at 06:00' : ''}, pre-launch screen, signed out: ${fails.length ? 'FAIL' : 'ok'}`);
  sock.close();
  done(fails.length ? 1 : 0);
} catch (e) { console.log('FAIL', e.message); done(1); }

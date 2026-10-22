// Headless page check over the Chrome DevTools protocol: loads the page, fails on console errors,
// exceptions or HTTP errors, prints the rendered state and writes a full-page screenshot.
// Usage: node --experimental-websocket tests/page-check.mjs http://localhost:8199/ [out.png] [width]
// (serve the repo with nginx.conf first; Web Serial needs https or localhost).
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
const url = process.argv[2], out = process.argv[3] || 'page-check.png', width = +(process.argv[4] || 1280);
const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=9333',
  `--window-size=${width},900`, `--user-data-dir=${process.env.TMPDIR || '/tmp'}/lv-page-check-${process.pid}`, 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws;
for(let i = 0; i < 50 && !ws; i++){ try{ const l = await (await fetch('http://127.0.0.1:9333/json')).json(); const p = l.find(t => t.type === 'page'); if(p) ws = p.webSocketDebuggerUrl; }catch{} await sleep(200); }
const sock = new WebSocket(ws); await new Promise(r => sock.onopen = r);
let id = 0; const pending = new Map(); const problems = []; const logs = [];
sock.onmessage = e => { const m = JSON.parse(e.data);
  if(m.id && pending.has(m.id)){ pending.get(m.id)(m); pending.delete(m.id); return; }
  if(m.method === 'Runtime.consoleAPICalled'){ const t = m.params.args.map(a => a.value ?? a.description).join(' '); logs.push(`${m.params.type}: ${t}`); if(['error','warning'].includes(m.params.type)) problems.push(t); }
  if(m.method === 'Runtime.exceptionThrown') problems.push('exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
  if(m.method === 'Log.entryAdded' && ['error','warning'].includes(m.params.entry.level)) problems.push(`log: ${m.params.entry.text} ${m.params.entry.url || ''}`);
  if(m.method === 'Network.responseReceived' && m.params.response.status >= 400) problems.push(`HTTP ${m.params.response.status} ${m.params.response.url}`);
};
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); sock.send(JSON.stringify({ id: i, method, params })); });
await send('Runtime.enable'); await send('Log.enable'); await send('Network.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url }); await sleep(2500);
const ev = async expr => (await send('Runtime.evaluate', { expression: expr, returnByValue: true })).result.result.value;
const dom = await ev(`JSON.stringify({ title: document.title, status: deviceStatus.textContent, latest: latestVersion.textContent, needs: releaseNeeds.textContent,
  options: [...releaseSelect.options].map(o => o.textContent), runtime: document.getElementById('runtimeState')?.textContent, uf2: document.querySelectorAll('.uf2').length,
  shaLinks: [...document.querySelectorAll('.uf2 a')].map(a => a.href), oplog: [...log.children].map(li => li.textContent), notesShown: !releaseNotes.hidden,
  sections: [...document.querySelectorAll('h2')].map(h => h.textContent), height: document.documentElement.scrollHeight, serial: 'serial' in navigator, secure: isSecureContext })`);
const h = JSON.parse(dom).height;
await send('Emulation.setDeviceMetricsOverride', { width, height: h, deviceScaleFactor: 1, mobile: false }); await sleep(300);
const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
console.log(JSON.stringify(JSON.parse(dom), null, 1)); console.log('PROBLEMS:', problems.length ? problems : 'none');
sock.close(); chrome.kill();
process.exit(problems.length ? 1 : 0);

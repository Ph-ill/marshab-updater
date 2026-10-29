// Settings (web/settings.js), clicked through against the mock Pico: the gear in the top bar
// (beside the battery and the flight day, a 44 px target with a label), what moved there from
// the crew page (Ship software, the home-screen steps, the Ship light, Sign out), the battery,
// Change your code under Sign out (refused without a session, a bad format, a wrong current
// code; the two new ones checked on the phone; the new code signs in, the old one doesn't),
// and Reset this ship at the bottom: refused without a session or the ship's number, the
// typed confirm, and after it the page's own storage gone and the first-time flow again.
// Story text is swapped for placeholders. Exits non-zero if a step fails.
//   game/web/shots_settings.sh OUTDIR   (mocks on 8059 with OTA and a battery, 8060 plain)
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
let fails = 0, ua = 0, jj0;
const ok = (what, c, why) => { console.log((c ? "ok   " : "FAIL ") + what + (c || why === undefined ? "" : " (" + why + ")")); if (!c) fails++; };
const blank = (x) => typeof x === "string" ? (x.length > 18 && x.includes(" ") ? PH : x) : Array.isArray(x) ? x.map(blank)
  : x && typeof x === "object" ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v)])) : x;
const ANDROID = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36";
async function page(port, { width = 390, height = 844, signin = true, android = false } = {}) {
  const ctx = await browser.newContext({ userAgent: `${android ? ANDROID : "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"} set/${ua++}`,
    viewport: { width, height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: "light", timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); fails++; });
  // Past the install guide (web/funnel.js), as after "Play in this browser this time".
  await p.addInitScript(() => sessionStorage.setItem("lv.here", "1"));
  await p.addInitScript(() => { const s = CSS.supports.bind(CSS); CSS.supports = (...a) => /anchor-name/.test(a.join("")) ? false : s(...a); });
  for (const [path, keys] of [["/text.json", ["cards", "epi", "reread", "notes", "reveal", "voice", "core", "patches"]], ["/engage.json", ["drops", "jobs", "file"]]]) {
    await p.route(`**${path}*`, async (route) => {
      const j = await (await route.fetch()).json();
      for (const k of keys) if (k in j) j[k] = blank(j[k]);
      if (j.cards) j.cards = j.cards.map((c) => ({ ...c, t: "Placeholder. " + PH, o: c.o.map((o) => ["Placeholder option", PH, ...o.slice(2)]) }));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(j) });
    });
  }
  await p.route("https://raw.githubusercontent.com/**", (r) => r.abort("internetdisconnected"));
  await p.goto(`http://localhost:${port}/?day=22`);
  await p.addStyleTag({ content: ":root{--sb:34px}" });
  if (signin) await signIn(p);
  return p;
}
async function signIn(p) {
  await p.waitForSelector("[data-who]");
  await p.click('[data-who="0"]');
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector("#dock nav, .kick.big");
  const first = !!(await p.$(".kick.big"));
  if (first) { await p.click("#dock .btn"); await p.waitForSelector(".kick.big", { state: "detached" }); }
  if (await p.$(".tut")) { await p.click("[data-tut=skip]"); await p.waitForSelector(".tut", { state: "detached" }); }
  await p.waitForSelector("#dock nav");
  return first;
}
async function shot(p, name, full = false) {
  await p.evaluate((ph) => { for (const li of document.querySelectorAll(".log li, .epi p")) li.textContent = ph; }, PH);
  await p.waitForTimeout(150);
  const v = p.viewportSize(), f = `${out}/${name}-light-${v.width}x${v.height}${full ? "-full" : ""}.png`;
  await p.screenshot({ path: f, fullPage: full });
  console.log(f);
}
const goto = (p, r) => p.evaluate((r) => go(r), r);
const center = (p, sel) => p.evaluate((s) => document.querySelector(s).scrollIntoView({ block: "center" }), sel);
const post = (p, body, token = true) => p.evaluate(async ([b, t]) => {
  const r = await fetch("/api/reset", { method: "POST", headers: t ? { "X-Crew-Token": tok, "Content-Type": "application/json" } : { "Content-Type": "application/json" }, body: b });
  return r.status;
}, [body, token]);

// 1. The gear: beside the battery and the flight day, on every signed-in screen.
let p = await page(8059);
await p.waitForFunction(() => !!OS_);
const g = await p.evaluate(() => {
  const b = document.querySelector("#top .gear"), r = b.getBoundingClientRect(), s = b.parentElement;
  return { label: b.getAttribute("aria-label"), w: r.width, h: r.height, inSpan: s.matches("#top>span"), bat: !!s.querySelector(".bat"), fd: /FD \d+/.test(s.textContent),
    last: s.lastElementChild === b, icon: b.querySelector("svg path").getAttribute("d").length > 20, top: document.querySelector("#top").getBoundingClientRect().height };
});
ok("gear: labelled Settings", g.label === "Settings");
ok("gear: a 44 px target", g.w >= 44 && g.h >= 44);
ok("gear: after the battery % and FD, in the top bar's right side", g.inSpan && g.bat && g.fd && g.last);
ok("gear: the top bar keeps its height", Math.round(g.top) === 48);
for (const r of ["crew", "log", "file"]) {
  await goto(p, r);
  ok(`gear on ${r}`, !!(await p.$("#top .gear")));
}
await goto(p, "home");
await shot(p, "set-01-home-gear-in-top-bar");
// The crew page is only the crew now.
await goto(p, "crew");
ok("crew page: no Ship light, Sign out, Ship software or Add to home screen", !(await p.$("#v [data-led], #v [data-out], #v [data-go=sw], #v [data-go=a2h], #v [data-go=set]")));
// 2. Settings: the sections, in order, the four tabs as they were.
await p.click("#top .gear");
await p.waitForSelector("#set-rst");
const secs = await p.$$eval("#v section", (s) => s.map((e) => e.id));
ok("Settings: Ship software, Home screen icon, Ship light, Battery, Sign out, Your code, Reset (last)", secs.filter((x) => x !== "set-live").join() === "set-sw,set-a2h,set-led,set-bat,set-out,set-code,set-rst"
  && (!secs.includes("set-live") || secs.indexOf("set-live") === secs.indexOf("set-out") - 1), secs.join());
// (Ship-to-ship, 0.3.0: its section sits before Sign out; empty here, no /api/live on this mock.)
ok("Settings: the gear says where you are", await p.$eval("#top .gear", (e) => e.getAttribute("aria-current") === "page"));
ok("Settings: the four tabs, none current", (await p.$$eval("#dock nav button", (b) => b.map((x) => x.dataset.go + (x.hasAttribute("aria-current") ? "*" : "")))).join() === "home,crew,log,file");
ok("Ship software: installed, channel, available, checked, check button", await p.$eval("#set-sw", (e) => /Installed\s*0\.2\.0/.test(e.textContent) && /Channel/.test(e.textContent) && /Available/.test(e.textContent) && /Checked/.test(e.textContent) && !!e.querySelector("[data-ota=check]")));
ok("Home screen icon: the steps for this browser", await p.$eval("#set-a2h", (e) => !!e.querySelector(".a2s") && /Add to Home Screen/.test(e.textContent)));
ok("Battery: 72 %, 3.95 V, charging", await p.$eval("#set-bat", (e) => /Charge\s*72%/.test(e.textContent) && /3\.95 V/.test(e.textContent) && /Charging\s*Yes/.test(e.textContent)));
ok("Reset: a danger button", await p.$eval("#set-rst [data-rst=ask]", (e) => e.classList.contains("dgr") && getComputedStyle(e).color !== getComputedStyle(document.body).color));
// The charging bolt follows the cable within seconds (web/batt.js's 5 s look at /api/bat),
// redrawn in place: the rest of the page stays the same nodes.
await p.evaluate(() => { window.__keep = document.querySelector("#set-sw"); return fetch("/api/bat?set=72,3950,0"); });
const bolt = () => p.evaluate(() => !!document.querySelector("#top .bat .bati path"));
ok("Battery: charging shows the bolt", await bolt());
await p.waitForFunction(() => !document.querySelector("#top .bat .bati path") && /Charging\s*No/.test(document.querySelector("#set-bat").textContent), null, { timeout: 12000 }).then(() => true, () => false).then((r) => ok("Battery: unplugged, no bolt within 12 s, two 5 s looks (top bar and Settings)", r));
await p.evaluate(() => fetch("/api/bat?set=73,4010,1"));
const t0 = Date.now();
await p.waitForFunction(() => !!document.querySelector("#top .bat .bati path") && /Charging\s*Yes/.test(document.querySelector("#set-bat").textContent) && /73%/.test(document.querySelector("#top .bat").textContent), null, { timeout: 12000 }).then(() => true, () => false).then((r) => ok("Battery: plugged in, the bolt and 73% back within 12 s (" + (Date.now() - t0) + " ms)", r));
ok("Battery: redrawn in place, not the whole page", await p.evaluate(() => window.__keep === document.querySelector("#set-sw")));
await p.evaluate(() => fetch("/api/bat?set=72,3950,1"));
await p.waitForFunction(() => /72%/.test(document.querySelector("#top .bat").textContent), null, { timeout: 12000 });
await shot(p, "set-02-settings-top");
await shot(p, "set-03-settings", true);
// The Ship light from here.
await p.click("#set-led [data-led]");
await p.waitForFunction(() => S.led === true && document.querySelector("#set-led [data-led]")?.textContent.includes("Ship light: on"));
ok("Ship light: on from Settings", true);
await center(p, "#set-led");
await shot(p, "set-04-ship-light-on-battery");
await p.click("#set-led [data-led]");
await p.waitForFunction(() => S.led === false && document.querySelector("#set-led [data-led]")?.textContent.includes("Ship light: off"));
// 2a. Test light (board/lvledtest.py; the mock answers as the ship does): under the switch,
// works with the light off; "Testing" with a bar for the ship's ms, repainted in place; a
// tap meanwhile does nothing and the ship says 429; back to "Test light" after.
const ledReq = (p, token = true) => p.evaluate(async (t) => {
  const r = await fetch("/api/led/test", { method: "POST", headers: t ? { "X-Crew-Token": tok, "Content-Type": "application/json" } : { "Content-Type": "application/json" }, body: "{}" });
  return [r.status, await r.json()];
}, token);
await center(p, "#set-led");
ok("Test light: under the Ship light switch, a quiet button", await p.$eval("#set-led", (e) => { const b = e.querySelector("[data-ledt]"), t = e.querySelector("[data-led]"); return !!b && b.classList.contains("sec") && /Test light/i.test(b.textContent) && !!(t.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) && !b.disabled; }));
ok("Test light: says what it does, and that it works with the light off", await p.$eval("#ledts", (e) => /three blinks/i.test(e.textContent) && /light off/i.test(e.textContent)));
ok("Test light: the light is off and the button is there", await p.evaluate(() => S.led === false && !!document.querySelector("[data-ledt]")));
let [lst] = await ledReq(p, false);
ok("Test light: refused without a session (401)", lst === 401);
await shot(p, "set-l1-test-light");
const t0l = Date.now();
await p.evaluate(() => { window.__keep = document.querySelector("#set-sw"); });
await p.click("[data-ledt]");
await p.waitForFunction(() => { const b = document.querySelector("[data-ledt]"); return b && b.disabled && b.getAttribute("aria-busy") === "true" && /Testing/i.test(b.textContent) && !!b.querySelector(".ledbar"); });
ok("Test light: \"Testing\" at once, disabled, a progress bar", true);
ok("Test light: tells you to look at the ship", await p.$eval("#ledts", (e) => /Look at LV-\d now/.test(e.textContent)));
await p.waitForTimeout(900);
await center(p, "#set-led");
await shot(p, "set-l2-testing");
await p.emulateMedia({ colorScheme: "dark" });
await p.waitForTimeout(150);
await p.screenshot({ path: `${out}/set-l2-testing-dark-390x844.png` });
console.log(`${out}/set-l2-testing-dark-390x844.png`);
await p.emulateMedia({ colorScheme: "light" });
[lst, jj0] = await ledReq(p);
ok("Test light: a second tap while it plays is 429 with the ms left", lst === 429 && jj0.ms > 8000 && jj0.ms <= 10000, [lst, jj0]);
await p.click("[data-ledt]", { force: true });
ok("Test light: still testing after another tap", await p.$eval("[data-ledt]", (b) => b.disabled));
await p.waitForFunction(() => { const b = document.querySelector("[data-ledt]"); return b && !b.disabled && /Test light/i.test(b.textContent); }, null, { timeout: 14000 });
const tl = Date.now() - t0l;
ok("Test light: back after 10 s (" + tl + " ms)", tl >= 9800 && tl <= 12500);
ok("Test light: says it's finished and what the light is back to", await p.$eval("#ledts", (e) => /Finished\. The light is back to off\./.test(e.textContent)));
ok("Test light: repainted in place, not the whole page", await p.evaluate(() => window.__keep === document.querySelector("#set-sw")));
await center(p, "#set-led");
await shot(p, "set-l3-test-finished");
// With the light on, the same button; the switch and the test don't get in each other's way.
await p.click("#set-led [data-led]");
await p.waitForFunction(() => S.led === true);
await p.click("[data-ledt]");
await p.waitForFunction(() => document.querySelector("[data-ledt]")?.disabled);
await center(p, "#set-led");
await shot(p, "set-l4-testing-light-on");
await p.waitForFunction(() => { const b = document.querySelector("[data-ledt]"); return b && !b.disabled && /back to on/.test(document.querySelector("#ledts").textContent); }, null, { timeout: 14000 });
ok("Test light: with the light on, finished and back to on", true);
await p.click("#set-led [data-led]");
await p.waitForFunction(() => S.led === false && document.querySelector("#set-led [data-led]")?.textContent.includes("Ship light: off"));
// 2b. Change your code: under Sign out, above Reset; the old code, then the new one twice.
const codeReq = (p, body, token = true) => p.evaluate(async ([b, t]) => {
  const r = await fetch("/api/code", { method: "POST", headers: t ? { "X-Crew-Token": tok, "Content-Type": "application/json" } : { "Content-Type": "application/json" }, body: JSON.stringify(b) });
  return [r.status, await r.json()];
}, [body, token]);
const typeCode = async (p, a, b, c) => { await p.fill("#chg0", a); await p.fill("#chg1", b); await p.fill("#chg2", c); };
const chgErrText = (p) => p.$eval("#chge", (e) => e.textContent);
await center(p, "#set-code");
ok("Your code: a quiet row with Change your code, and says it's this ship only", await p.$eval("#set-code", (e) => /Change your code/.test(e.textContent) && /LV-\d only/.test(e.textContent) && /Other ships keep your current code/.test(e.textContent) && e.querySelector("[data-chg=ask]").classList.contains("sec")));
await shot(p, "set-c1-your-code-row");
await p.click("[data-chg=ask]");
await p.waitForSelector("#chg2");
const f = await p.$$eval("#set-code input", (i) => i.map((x) => [x.type, x.inputMode, x.getAttribute("autocomplete"), x.maxLength, x.pattern, getComputedStyle(x).webkitTextSecurity || ""]));
ok("form: three fields, numeric keypad, 4 digits, masked, no autofill", f.length === 3 && f.every(([t, im, ac, ml, pt, sec]) => t === "text" && im === "numeric" && ac === "off" && ml === 4 && pt === "[0-9]*" && sec === "disc"));
ok("form: labelled, current code first", (await p.$$eval("#set-code label", (l) => l.map((x) => x.textContent))).join("|") === "Your code now|New code|New code again");
ok("form: the current-code field has focus", await p.evaluate(() => document.activeElement?.id === "chg0"));
await p.keyboard.type("12a3");
ok("form: letters don't go in", await p.$eval("#chg0", (e) => e.value === "123"));
await p.fill("#chg0", "");
await center(p, "#set-code");
await shot(p, "set-c2-change-code-form");
await p.emulateMedia({ colorScheme: "dark" });
await p.waitForTimeout(150);
await p.screenshot({ path: `${out}/set-c2-change-code-form-dark-390x844.png` });
console.log(`${out}/set-c2-change-code-form-dark-390x844.png`);
await p.emulateMedia({ colorScheme: "light" });
// Caught on the phone, before asking the ship.
const asked = [];
p.on("request", (r) => { if (r.url().includes("/api/code")) asked.push(r.url()); });
await typeCode(p, "1234", "5678", "5679");
await p.click("[data-chg=go]");
await p.waitForFunction(() => /don't match/.test(document.querySelector("#chge")?.textContent || ""));
ok("mismatched new codes: caught on the phone, not sent", asked.length === 0);
ok("mismatched: the new fields are cleared and marked, the new-code field focused", await p.evaluate(() => $("chg1").value === "" && $("chg2").value === "" && $("chg1").classList.contains("bad") && document.activeElement?.id === "chg1" && $("chg0").value === "1234"));
await center(p, "#set-code");
await shot(p, "set-c3-change-code-mismatch");
await typeCode(p, "1234", "56", "56");
await p.click("[data-chg=go]");
ok("too short: caught on the phone", /4 digits/.test(await chgErrText(p)) && asked.length === 0);
await typeCode(p, "1234", "1234", "1234");
await p.click("[data-chg=go]");
ok("same as the current one: caught on the phone", /same as your current/.test(await chgErrText(p)) && asked.length === 0);
// The ship's own refusals.
let [st, jj] = await codeReq(p, { old: "1234", new: "5678" }, false);
ok("ship: no session is 401", st === 401);
[st, jj] = await codeReq(p, { old: "1234", new: "56789" });
ok("ship: 5 digits is 400", st === 400 && /4 digits/.test(jj.err));
[st, jj] = await codeReq(p, { old: "1234", new: "56a8" });
ok("ship: a letter is 400", st === 400);
[st, jj] = await codeReq(p, { old: "1234", new: "1234" });
ok("ship: the same code is 400", st === 400);
asked.length = 0;
await typeCode(p, "9999", "5678", "5678");
await p.click("[data-chg=go]");
await p.waitForFunction(() => /isn't your current code/.test(document.querySelector("#chge")?.textContent || ""));
ok("wrong current code: the ship says so and how many tries are left", /4 tries left/.test(await chgErrText(p)) && asked.length === 1, await chgErrText(p));
ok("wrong current code: still signed in", await p.evaluate(() => !!tok && route === "set"));
await center(p, "#set-code");
await shot(p, "set-c4-change-code-wrong");
await typeCode(p, "1234", "5678", "5678");
await p.click("[data-chg=go]");
await p.waitForSelector("#set-code .ok");
ok("success: says so, you're still signed in, the form is closed", await p.evaluate(() => /new code/.test($("set-code").textContent) && !!tok && !$("chg0") && document.activeElement?.dataset.chg === "ask"));
ok("success: still signed in on the ship", (await p.evaluate(async () => (await fetch("/api/state", { headers: { "X-Crew-Token": tok } })).status)) === 200);
await center(p, "#set-code");
await shot(p, "set-c5-change-code-done");
const login = (p, pin) => p.evaluate(async (pin) => (await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ crew: 0, pin }) })).status, pin);
ok("after: the old code no longer signs in", (await login(p, "1234")) === 403);
ok("after: the new one does", (await login(p, "5678")) === 200);
[st, jj] = await codeReq(p, { old: "5678", new: "1234" });
ok("and back to 1234 for the rest of the run", st === 200 && (await login(p, "1234")) === 200);
await p.click("[data-chg=ask]");
await p.waitForSelector("#chg0");
await p.click("[data-chg=no]");
ok("Cancel closes the form", !(await p.$("#chg0")) && !!(await p.$("[data-chg=ask]")));
// 3. Reset this ship: the ship refuses without a session and without its number.
const no = await p.evaluate(() => S.here + 1);
ok("reset refused without a session: 401", (await post(p, JSON.stringify({ confirm: no }), false)) === 401);
ok("reset refused without the confirm: 403", (await post(p, "{}")) === 403);
ok("reset refused with another ship's number: 403", (await post(p, JSON.stringify({ confirm: no + 1 }))) === 403);
ok("still signed in after the refusals", (await p.evaluate(async () => (await fetch("/api/state", { headers: { "X-Crew-Token": tok } })).status)) === 200);
await p.click("[data-rst=ask]");
await p.waitForSelector("#rstn");
ok("reset: asks for the ship's number, Reset now off", await p.$eval("[data-rst=go]", (e) => e.disabled) && await p.$eval(".rstl", (e, n) => e.textContent.includes(String(n)), no));
await p.fill("#rstn", String(no + 1));
ok("reset: a wrong number keeps it off", await p.$eval("[data-rst=go]", (e) => e.disabled));
await p.fill("#rstn", String(no));
ok("reset: the right number turns it on", await p.$eval("[data-rst=go]", (e) => !e.disabled));
await center(p, "#set-rst");
await shot(p, "set-05-reset-confirm");
await p.evaluate(() => { localStorage.setItem("lv.a2hs", "1"); localStorage.setItem("lv-briefed", "1"); });
ok("before: this page keeps things in storage", await p.evaluate(() => localStorage.length >= 2 && !!localStorage.getItem("lv.ota")));
const oldTok = await p.evaluate(() => tok);
await p.click("[data-rst=go]");
await p.waitForSelector(".kick h1");
await p.waitForFunction(() => document.querySelector("#v h1")?.textContent === "Starting over");
ok("reset: this page's storage is cleared", await p.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0));
ok("reset: the ship forgot the session", (await p.evaluate(async (t) => (await fetch("/api/state", { headers: { "X-Crew-Token": t } })).status, oldTok)) === 401);
await shot(p, "set-06-reset-restarting");
await p.waitForSelector("[data-who]", { timeout: 30000 });
ok("reset: back at the sign-in, nothing kept", await p.evaluate(() => route === "hello" && !localStorage.getItem("lv.a2hs") && !localStorage.getItem("lv-briefed") && location.hash === ""));
ok("reset: the first-time flow again", await signIn(p));
// 4. Sign out from Settings.
await goto(p, "set");
await center(p, "#set-out");
await p.click("#set-out [data-out]");
await p.waitForSelector("[data-who]");
ok("Sign out from Settings", await p.evaluate(() => !tok && route === "hello"));
await p.context().close();

// 5. A ship without a battery or OTA, at 320 px: no battery section; the bar fits.
p = await page(8060, { width: 320, height: 640 });
await p.click("#top .gear");
await p.waitForSelector("#set-rst");
ok("no battery: no Battery section", !(await p.$("#set-bat")));
ok("no OTA: Ship software says it needs one USB install", await p.$eval("#set-sw", (e) => /one install over USB/.test(e.textContent)));
ok("320 px: the top bar fits", await p.$eval("#top", (e) => e.scrollWidth <= e.clientWidth && [...e.children].every((c) => c.getBoundingClientRect().right <= innerWidth + 0.5)));
ok("320 px: nothing in Settings is wider than the screen", await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
await shot(p, "set-07-settings-no-battery");
await p.click("[data-rst=ask]");
await center(p, "#set-rst");
await shot(p, "set-08-reset-confirm");
await p.context().close();
// Test light playing on an Android phone (412 px), as on the iPhone above: three blinks, then
// three slow breaths, 10 s; the bar runs for all of it.
p = await page(8060 - 1, { width: 412, height: 915, android: true });
await goto(p, "set");
await p.waitForSelector("[data-ledt]");
const t0a = Date.now();
await p.click("[data-ledt]");
await p.waitForFunction(() => document.querySelector("[data-ledt]")?.getAttribute("aria-busy") === "true");
await p.waitForTimeout(900);
await center(p, "#set-led");
ok("412 Android: Testing, the bar's animation as long as the ship's 10 s", await p.$eval(".ledbar", (b) => { const d = parseFloat(b.style.animationDuration); return d > 8000 && d <= 10000; }), await p.$eval(".ledbar", (b) => b.style.animationDuration));
await shot(p, "set-l2-testing");
await p.waitForFunction(() => { const b = document.querySelector("[data-ledt]"); return b && !b.disabled; }, null, { timeout: 14000 });
ok("412 Android: back after 10 s", Date.now() - t0a >= 9800);
await p.context().close();
// ...and with the battery at 320 px: the top bar still fits, gear included.
p = await page(8060 - 1, { width: 320, height: 640 });
ok("320 px with the battery: the top bar fits", await p.$eval("#top", (e) => !!e.querySelector(".bat") && e.scrollWidth <= e.clientWidth && e.querySelector(".gear").getBoundingClientRect().right <= innerWidth + 0.5));
await shot(p, "set-09-home-gear-battery");
await goto(p, "set");
await p.waitForSelector("[data-ledt]");
ok("320 px: Test light fits on one line", await p.$eval("[data-ledt]", (b) => b.scrollWidth <= b.clientWidth && b.getBoundingClientRect().height <= 60));
await p.context().close();
// ...and on Android, where the Full screen button (web/fullscreen.js) sits before the gear.
p = await page(8060 - 1, { width: 320, height: 640, android: true });
ok("320 px Android with the battery: the top bar fits, Full screen and gear included", await p.$eval("#top", (e) => !!e.querySelector(".bat") && !!e.querySelector(".fsb") && e.scrollWidth <= e.clientWidth && e.querySelector(".gear").getBoundingClientRect().right <= innerWidth + 0.5 && e.querySelector("b").getBoundingClientRect().right < e.querySelector("span").getBoundingClientRect().left));
await shot(p, "set-10-android-home-fullscreen-gear-battery");
await p.context().close();
await browser.close();
console.log(fails ? `FAIL ${fails}` : "settings shots: all ok");
process.exit(fails ? 1 : 0);

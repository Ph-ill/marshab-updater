// Settings (web/settings.js), clicked through against the mock Pico: the gear in the top bar
// (beside the battery and the flight day, a 44 px target with a label), what moved there from
// the crew page (Ship software, the home-screen steps, the Ship light, Sign out), the battery,
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
let fails = 0, ua = 0;
const ok = (what, c) => { console.log((c ? "ok   " : "FAIL ") + what); if (!c) fails++; };
const blank = (x) => typeof x === "string" ? (x.length > 18 && x.includes(" ") ? PH : x) : Array.isArray(x) ? x.map(blank)
  : x && typeof x === "object" ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v)])) : x;
const ANDROID = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36";
async function page(port, { width = 390, height = 844, signin = true, android = false } = {}) {
  const ctx = await browser.newContext({ userAgent: `${android ? ANDROID : "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"} set/${ua++}`,
    viewport: { width, height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: "light", timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); fails++; });
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
ok("Settings: Ship software, Home screen icon, Ship light, Battery, Sign out, Reset (last)", secs.join() === "set-sw,set-a2h,set-led,set-bat,set-out,set-rst");
ok("Settings: the gear says where you are", await p.$eval("#top .gear", (e) => e.getAttribute("aria-current") === "page"));
ok("Settings: the four tabs, none current", (await p.$$eval("#dock nav button", (b) => b.map((x) => x.dataset.go + (x.hasAttribute("aria-current") ? "*" : "")))).join() === "home,crew,log,file");
ok("Ship software: installed, channel, available, checked, check button", await p.$eval("#set-sw", (e) => /Installed\s*0\.2\.0/.test(e.textContent) && /Channel/.test(e.textContent) && /Available/.test(e.textContent) && /Checked/.test(e.textContent) && !!e.querySelector("[data-ota=check]")));
ok("Home screen icon: the steps for this browser", await p.$eval("#set-a2h", (e) => !!e.querySelector(".a2s") && /Add to Home Screen/.test(e.textContent)));
ok("Battery: 72 %, 3.95 V, charging", await p.$eval("#set-bat", (e) => /Charge\s*72%/.test(e.textContent) && /3\.95 V/.test(e.textContent) && /Charging\s*Yes/.test(e.textContent)));
ok("Reset: a danger button", await p.$eval("#set-rst [data-rst=ask]", (e) => e.classList.contains("dgr") && getComputedStyle(e).color !== getComputedStyle(document.body).color));
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
// ...and with the battery at 320 px: the top bar still fits, gear included.
p = await page(8060 - 1, { width: 320, height: 640 });
ok("320 px with the battery: the top bar fits", await p.$eval("#top", (e) => !!e.querySelector(".bat") && e.scrollWidth <= e.clientWidth && e.querySelector(".gear").getBoundingClientRect().right <= innerWidth + 0.5));
await shot(p, "set-09-home-gear-battery");
await p.context().close();
// ...and on Android, where the Full screen button (web/fullscreen.js) sits before the gear.
p = await page(8060 - 1, { width: 320, height: 640, android: true });
ok("320 px Android with the battery: the top bar fits, Full screen and gear included", await p.$eval("#top", (e) => !!e.querySelector(".bat") && !!e.querySelector(".fsb") && e.scrollWidth <= e.clientWidth && e.querySelector(".gear").getBoundingClientRect().right <= innerWidth + 0.5 && e.querySelector("b").getBoundingClientRect().right < e.querySelector("span").getBoundingClientRect().left));
await shot(p, "set-10-android-home-fullscreen-gear-battery");
await p.context().close();
await browser.close();
console.log(fails ? `FAIL ${fails}` : "settings shots: all ok");
process.exit(fails ? 1 : 0);

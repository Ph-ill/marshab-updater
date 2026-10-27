// The home-screen card and Settings' Home screen icon section (web/a2hs.js, settings.js), clicked through against the mock Pico with
// each phone browser's user agent: iOS Safari (18 and 26), the iOS captive sheet, Chrome
// and the sign-in window on Android, Samsung Internet; and none of it on a computer or
// once the game runs from the icon. The page is loaded as http://192.168.4.1/ (requests
// handed to the mock), so Chrome judges the real origin: the test reads back that the
// manifest parses and that Chrome won't offer an install there (not a secure origin).
// Story text is swapped for placeholders. Exits non-zero if a step fails.
//   game/web/shots_a2hs.sh OUTDIR   (starts a mock on 8058)
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const MOCK = "http://localhost:8058", SHIP = "http://192.168.4.1";
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
let fails = 0, n = 0;
const ok = (what, c) => { console.log((c ? "ok   " : "FAIL ") + what); if (!c) fails++; };
const UA = {
  ios: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1",
  ios26: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
  sheet: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
  and: "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
  awv: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP2A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.0.0 Mobile Safari/537.36",
  sam: "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/28.0 Chrome/130.0.0.0 Mobile Safari/537.36",
  desk: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
};
function blank(x) {
  if (typeof x === "string") return x.length > 18 && x.includes(" ") ? PH : x;
  if (Array.isArray(x)) return x.map(blank);
  if (x && typeof x === "object") return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v)]));
  return x;
}
async function page(kind, { standalone = false, ctx = null, insets = null, vp = null } = {}) {
  const android = /Android/.test(UA[kind]), desk = kind === "desk";
  vp = vp || (desk ? { width: 1280, height: 800 } : android ? { width: 412, height: 915 } : { width: 390, height: 844 });
  ctx = ctx || await browser.newContext({ userAgent: UA[kind] + ` a2/${n++}`, viewport: vp, deviceScaleFactor: desk ? 1 : 2,
    isMobile: !desk, hasTouch: !desk, colorScheme: "light", timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); fails++; });
  // Safari 18 has no anchor positioning (app.html tells it from 26 by that); Chrome has.
  if (kind === "ios") await p.addInitScript(() => { const s = CSS.supports.bind(CSS); CSS.supports = (...a) => /anchor-name/.test(a.join("")) ? false : s(...a); });
  // The phone's safe areas (status bar, home indicator), as real env() values.
  if (insets) await (await ctx.newCDPSession(p)).send("Emulation.setSafeAreaInsetsOverride", { insets });
  if (standalone === "ios") await p.addInitScript(() => Object.defineProperty(navigator, "standalone", { get: () => true }));
  // Chrome's media emulation has no display-mode, so answer that one query as an installed app would.
  if (standalone === "media") await p.addInitScript(() => { const m = matchMedia.bind(window);
    window.matchMedia = (q) => /display-mode:\s*standalone/.test(q) ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} } : m(q); });
  // The ship's address, served by the mock; story text blanked on the way.
  await p.route(SHIP + "/**", async (route) => {
    const u = new URL(route.request().url());
    let r;
    try { r = await route.fetch({ url: MOCK + u.pathname + u.search }); } catch { return; }   // page closed
    if (u.pathname === "/text.json" || u.pathname === "/engage.json") {
      const j = await r.json();
      for (const k of ["cards", "epi", "reread", "notes", "reveal", "voice", "core", "drops", "jobs", "file", "patches"]) if (k in j) j[k] = blank(j[k]);
      if (j.cards) j.cards = j.cards.map((c) => ({ ...c, t: "Placeholder. " + PH, o: c.o.map((o) => ["Placeholder option", PH, ...o.slice(2)]) }));
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(j) });
    }
    await route.fulfill({ response: r });
  });
  await p.goto(SHIP + "/?day=22");
  if (!insets) await p.addStyleTag({ content: ":root{--sb:34px}" });
  await p.waitForSelector("[data-who], #dock nav");
  if (await p.$("[data-who]")) {
    await p.click('[data-who="0"]');
    for (const k of "1234") await p.click(`[data-key="${k}"]`);
    await p.waitForSelector("#dock nav, .kick.big");
    if (await p.$(".kick.big")) { await p.click("#dock .btn"); await p.waitForSelector(".kick.big", { state: "detached" }); }
    if (await p.$(".tut")) { await p.click("[data-tut=skip]"); await p.waitForSelector(".tut", { state: "detached" }); }
  }
  await p.waitForSelector("#dock nav");
  return p;
}
async function shot(p, name) {
  await p.evaluate((ph) => { for (const li of document.querySelectorAll(".log li, .epi p")) li.textContent = ph; }, PH);
  await p.waitForTimeout(150);
  const v = p.viewportSize(), f = `${out}/${name}-light-${v.width}x${v.height}.png`;
  await p.screenshot({ path: f });
  console.log(f);
}
const close = async (p) => { await p.unrouteAll({ behavior: "ignoreErrors" }); await p.context().close(); };
const goto = (p, r) => p.evaluate((r) => go(r), r);
const card = (p) => p.$eval(".a2h", (e) => e.textContent).catch(() => null);
const center = (p, sel) => p.evaluate((s) => document.querySelector(s).scrollIntoView({ block: "center" }), sel);

// 1. iOS Safari: the card on the home screen; Got it hides it for good.
let p = await page("ios");
let t = await card(p);
ok("iOS Safari: card says Share > Add to Home Screen", !!t && /Share/.test(t) && /bottom of Safari/.test(t) && /Add to Home Screen/.test(t) && /full screen/.test(t));
ok("the card says the icon only works on the ship's Wi-Fi", !!t && /only works while your phone is on the ship's Wi-Fi/.test(t));
ok("the card has the share icon", !!(await p.$(".a2h svg.a2i")));
await center(p, ".a2h");
await shot(p, "a2hs-01-ios-safari-card");
await p.click("[data-a2h=ok]");
ok("Got it removes the card", !(await p.$(".a2h")));
await p.reload();
await p.waitForSelector("#dock nav");
ok("dismissed stays dismissed after a reload", !(await p.$(".a2h")) && (await p.evaluate(() => localStorage.getItem("lv.a2hs"))) === "1");
await goto(p, "crew");
ok("your crew page has no Add to home screen row", !(await p.$("#v [data-go=a2h]")));
await p.click("#top .gear");
await p.waitForSelector("#set-a2h .a2s");
ok("Settings has the steps and what to expect", await p.$eval("#set-a2h", (e) => /Home screen icon/.test(e.textContent) && /2 steps/.test(e.textContent) && /bottom of Safari/.test(e.textContent) && /only works while your phone is on the ship's Wi-Fi/.test(e.textContent)));
await center(p, "#set-a2h");
await shot(p, "a2hs-02-ios-settings-gear");
await goto(p, "a2h");
ok("the old #a2h route lands in Settings", await p.evaluate(() => route === "set" && location.hash === "#set"));
await center(p, "#set-a2h");
await shot(p, "a2hs-03-ios-safari-settings-section");
// What Chrome makes of the ship's address: the manifest parses, no install offered.
const cdp = await p.context().newCDPSession(p);
const mf = await cdp.send("Page.getAppManifest", {});
ok("Chrome reads the manifest from 192.168.4.1 with no errors", mf.url === SHIP + "/app.webmanifest" && mf.errors.length === 0 && JSON.parse(mf.data || "{}").name === "The Long Voyage" && JSON.parse(mf.data || "{}").short_name === "The Long Voyage");
const ie = await cdp.send("Page.getInstallabilityErrors").catch((e) => ({ installabilityErrors: [{ errorId: "unavailable: " + e.message }] }));
const ids = ie.installabilityErrors.map((e) => e.errorId);
console.log("     Chrome installability on http://192.168.4.1: " + JSON.stringify(ids));
ok("Chrome won't offer a one-tap install on http (not a secure origin)", ids.includes("not-from-secure-origin"));
await close(p);

// 2. iOS 26 Safari, as on a real iPhone: page menu > Share > View More > Add to Home Screen.
p = await page("ios26");
t = await card(p);
ok("iOS 26: page menu, Share; View More, Add to Home Screen; Open as Web App, Add", !!t && /3 steps/i.test(t) && /Tap\s+in the address bar, then Share\s*\. Share in Safari's toolbar\? Tap that\./.test(t) && /Tap View More\s*, then Add to Home Screen\./.test(t) && /Keep Open as Web App on, then tap Add\./.test(t));
ok("iOS 26: page menu, share and View More icons inline", (await p.$$eval(".a2h .a2s svg.a2i", (s) => s.map((e) => e.getAttribute("aria-label")))).join() === "page menu,Share,View More");
await center(p, ".a2h");
await shot(p, "a2hs-04-ios26-safari-card");
await close(p);

// 3. The iOS captive sheet: get to Safari first, with the address to type.
p = await page("sheet");
t = await card(p);
ok("iOS sheet: Cancel, Use Without Internet, Safari, the address", !!t && /Cancel/.test(t) && /Use Without Internet/.test(t) && /192\.168\.4\.1/.test(t) && /3 steps/.test(t));
await center(p, ".a2h");
await shot(p, "a2hs-05-ios-captive-sheet-card");
await p.click("[data-a2h=ok]");
ok("sheet: Got it hides it this visit", !(await p.$(".a2h")));
await close(p);

// 4. Android Chrome: menu > Add to Home screen; opens in a Chrome tab.
p = await page("and");
t = await card(p);
ok("Android Chrome: menu, Add to Home screen, Chrome tab", !!t && /top right of Chrome/.test(t) && /Add to Home screen/.test(t) && /Chrome tab/.test(t));
await center(p, ".a2h");
await shot(p, "a2hs-06-android-chrome-card");
await goto(p, "set");
await p.waitForSelector("#set-a2h .a2s");
await center(p, "#set-a2h");
await shot(p, "a2hs-07-android-chrome-settings-section");
await close(p);

// 5. Android's sign-in window: close it, open Chrome, type the address.
p = await page("awv");
t = await card(p);
ok("Android sign-in window: close it, Chrome, the address", !!t && /Close it/.test(t) && /Open Chrome/.test(t) && /192\.168\.4\.1/.test(t));
await center(p, ".a2h");
await shot(p, "a2hs-08-android-sign-in-window-card");
await close(p);

// 6. Samsung Internet.
p = await page("sam");
t = await card(p);
ok("Samsung Internet: Add page to > Home screen", !!t && /Add page to/.test(t));
await close(p);

// 7. Already on the home screen (iOS navigator.standalone, Android display-mode), or a computer: nothing.
for (const [kind, sa, what] of [["sheet", "ios", "opened from the icon on iOS"], ["and", "media", "opened from the icon on Android"], ["desk", false, "a computer"]]) {
  p = await page(kind, { standalone: sa });
  ok(`${what}: no card`, !(await p.$(".a2h")));
  await goto(p, "set");
  ok(`${what}: Settings has no steps, says why`, !(await p.$("#set-a2h .a2s")) && await p.$eval("#set-a2h", (e, d) => (d ? /phone's browser/ : /already playing from your home screen/).test(e.textContent), kind === "desk"));
  if (kind === "sheet") { await goto(p, "home"); await shot(p, "a2hs-09-ios-opened-from-icon-home"); }
  await close(p);
}
// 8. Where the manifest and Apple's web-app tags go: everywhere but iOS 26 (app.html).
const tags = (p) => p.evaluate(() => [!!document.querySelector('link[rel=manifest]'), !!document.querySelector('meta[name=apple-mobile-web-app-capable]')].join());
for (const [kind, want, what] of [["ios", "true,true", "iOS 18 Safari"], ["ios26", "false,false", "iOS 26 Safari"], ["sheet", "false,false", "iOS 26 sheet or icon"], ["and", "true,true", "Android Chrome"], ["desk", "true,true", "a computer"]]) {
  p = await page(kind, kind === "sheet" ? { standalone: "ios" } : {});
  ok(`${what}: manifest and web-app tags ${want === "true,true" ? "there" : "left out"}`, (await tags(p)) === want);
  ok(`${what}: the icon's name is The Long Voyage`, (await p.evaluate(() => [document.title, document.querySelector("meta[name=apple-mobile-web-app-title]")?.content ?? document.title].join())) === "The Long Voyage,The Long Voyage");
  await close(p);
}

// 9. Opened from the icon on iOS 26, with the phone's real safe areas (an iPhone 390x844,
// 47 px status bar, 34 px home indicator; and 402x874, 62/34, as on Phill's phone). The
// header clears the status bar, the dock reaches the bottom edge with the nav right above
// the home indicator, the action button sits on the nav, and nothing scrolls under them.
async function frame(p, W, H, st, sb, what) {
  const g = await p.evaluate(() => { const r = (s) => document.querySelector(s)?.getBoundingClientRect();
    const t = r("#top"), d = r("#dock"), nv = r("#dock nav"), a = r("#dock .act"), h = document.querySelector("#top > *").getBoundingClientRect();
    scrollTo(0, 1e6); const m = document.querySelector("main"), l = m.lastElementChild.getBoundingClientRect();
    const g = { top: t.top, topH: t.height, head: h.top, dock: d.bottom, dockTop: d.top, nav: nv.bottom, navTop: nv.top, act: a ? a.bottom : null, last: l.bottom, ih: innerHeight };
    scrollTo(0, 0); return g; });
  ok(`${what}: header under the status bar (${g.head} >= ${st})`, g.top === 0 && g.head >= st && Math.round(g.topH) === 48 + st);
  ok(`${what}: dock to the bottom edge, nav ${sb} px above it (${g.nav}/${g.dock} of ${H})`, g.ih === H && Math.round(g.dock) === H && Math.round(g.nav) === H - sb);
  ok(`${what}: the action button sits right on the nav`, g.act === null || Math.abs(g.act - g.navTop) <= 1);
  ok(`${what}: the end of the page scrolls clear of the dock (${Math.round(g.last)} <= ${Math.round(g.dockTop)})`, g.last <= g.dockTop + 0.5);
}
for (const [W, H, st, sb] of [[390, 844, 47, 34], [402, 874, 62, 34]]) {
  p = await page("sheet", { standalone: "ios", insets: { top: st, bottom: sb }, vp: { width: W, height: H } });
  for (const r of ["home", "file"]) {
    await goto(p, r); await p.waitForTimeout(100);
    await frame(p, W, H, st, sb, `iOS 26 icon ${W}x${H} ${r}`);
    if (W === 390) await shot(p, `a2hs-11-ios26-icon-after-${r}`);
  }
  await close(p);
}
// Before: the same page in the too-short window iOS 26 gave the old markup (the status bar's
// height missing at the bottom), drawn on the full screen. Simulated: Chrome can't make it.
p = await page("sheet", { standalone: "ios", insets: { top: 47, bottom: 34 }, vp: { width: 390, height: 844 - 47 } });
for (const r of ["home", "file"]) {
  await goto(p, r); await p.waitForTimeout(100);
  await p.evaluate((ph) => { for (const li of document.querySelectorAll(".log li, .epi p")) li.textContent = ph; }, PH);
  const png = (await p.screenshot()).toString("base64"), bg = await p.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const q = await p.context().newPage(); await q.setViewportSize({ width: 390, height: 844 });
  await q.setContent(`<meta name=viewport content="width=device-width,initial-scale=1"><body style="margin:0;background:${bg}"><img style="display:block;width:390px" src="data:image/png;base64,${png}">`);
  const f = `${out}/a2hs-10-ios26-icon-before-${r}-simulated-light-390x844.png`;
  await q.screenshot({ path: f }); console.log(f); await q.close();
}
await close(p);

// Normal Safari tabs and Android Chrome: no insets, the dock on the bottom edge.
for (const kind of ["ios26", "and"]) {
  p = await page(kind, { insets: { top: 0, bottom: 0 } });
  const v = p.viewportSize(), g = await p.evaluate(() => [document.querySelector("#dock").getBoundingClientRect().bottom, document.querySelector("#dock nav").getBoundingClientRect().bottom]);
  ok(`${kind === "and" ? "Android Chrome" : "iOS 26 Safari tab"}: dock and nav on the bottom edge`, Math.round(g[0]) === v.height && Math.round(g[1]) === v.height);
  await close(p);
}
await browser.close();
console.log(fails ? `FAIL ${fails}` : "home-screen shots: all ok");
process.exit(fails ? 1 : 0);

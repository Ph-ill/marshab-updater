// The home-screen card and screen (web/a2hs.js), clicked through against the mock Pico with
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
async function page(kind, { standalone = false, ctx = null } = {}) {
  const android = /Android/.test(UA[kind]), desk = kind === "desk";
  const vp = desk ? { width: 1280, height: 800 } : android ? { width: 412, height: 915 } : { width: 390, height: 844 };
  ctx = ctx || await browser.newContext({ userAgent: UA[kind] + ` a2/${n++}`, viewport: vp, deviceScaleFactor: desk ? 1 : 2,
    isMobile: !desk, hasTouch: !desk, colorScheme: "light", timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); fails++; });
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
      for (const k of ["cards", "epi", "reread", "notes", "reveal", "voice", "core", "drops", "jobs", "file"]) if (k in j) j[k] = blank(j[k]);
      if (j.cards) j.cards = j.cards.map((c) => ({ ...c, t: "Placeholder. " + PH, o: c.o.map((o) => ["Placeholder option", PH, ...o.slice(2)]) }));
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(j) });
    }
    await route.fulfill({ response: r });
  });
  await p.goto(SHIP + "/?day=22");
  await p.addStyleTag({ content: ":root{--sb:34px}" });
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
ok("your page still has Add to home screen", !!(await p.$("#v [data-go=a2h]")));
await center(p, "#v [data-go=a2h]");
await shot(p, "a2hs-02-ios-your-page-row");
await p.click("#v [data-go=a2h]");
await p.waitForSelector(".a2s");
ok("the screen has the steps and what to expect", await p.$eval("#v", (e) => /One tap to come aboard/.test(e.textContent) && /Sign in once/.test(e.textContent)));
await shot(p, "a2hs-03-ios-safari-screen");
// What Chrome makes of the ship's address: the manifest parses, no install offered.
const cdp = await p.context().newCDPSession(p);
const mf = await cdp.send("Page.getAppManifest", {});
ok("Chrome reads the manifest from 192.168.4.1 with no errors", mf.url === SHIP + "/app.webmanifest" && mf.errors.length === 0 && /Long Voyage/.test(mf.data || ""));
const ie = await cdp.send("Page.getInstallabilityErrors").catch((e) => ({ installabilityErrors: [{ errorId: "unavailable: " + e.message }] }));
const ids = ie.installabilityErrors.map((e) => e.errorId);
console.log("     Chrome installability on http://192.168.4.1: " + JSON.stringify(ids));
ok("Chrome won't offer a one-tap install on http (not a secure origin)", ids.includes("not-from-secure-origin"));
await close(p);

// 2. iOS 26 Safari: Share sits under the ... menu; keep Open as Web App on.
p = await page("ios26");
t = await card(p);
ok("iOS 26: More, then Share; Open as Web App", !!t && /beside the address/.test(t) && /Open as Web App/.test(t));
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
await goto(p, "a2h");
await p.waitForSelector(".a2s");
await shot(p, "a2hs-07-android-chrome-screen");
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
  await goto(p, "crew");
  ok(`${what}: no card, no row`, !(await p.$(".a2h")) && !(await p.$("#v [data-go=a2h]")));
  if (kind === "sheet") { await goto(p, "home"); await shot(p, "a2hs-09-ios-opened-from-icon-home"); }
  await close(p);
}
await browser.close();
console.log(fails ? `FAIL ${fails}` : "home-screen shots: all ok");
process.exit(fails ? 1 : 0);

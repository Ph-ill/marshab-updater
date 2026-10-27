// The home-screen funnel (web/funnel.js, board/lvfunnel.py), clicked through against the
// board's own server code (tests/phone_serve.py: main.py's /api/hello hook and lvfunnel as
// they are) with each phone's user agent, and screenshots of every screen: the captive
// pop-ups (iOS sheet, Android sign-in window) that only send you to the browser; the guide
// in Safari (iOS 26 and 18) and Chrome; the icon launch that marks the phone; the browser
// tab that then says you have the icon; and "Reset this ship" forgetting it. The page is
// loaded as http://192.168.4.1/ (requests handed to the server), so the drawings show the
// real address. Every request comes from 127.0.0.1, so it's one phone to the ship: the
// script deletes the funnel's store (build/e2e-data/funnel.bin) between phones. Story text
// is swapped for placeholders. Exits non-zero if a step fails.
//   game/web/shots_funnel.sh OUTDIR   (starts tests/phone_serve.py on 8059)
import { createRequire } from "module";
import { rmSync } from "fs";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const SRV = "http://127.0.0.1:" + (process.env.PORT || 8059), SHIP = "http://192.168.4.1";
const STORE = "build/e2e-data/funnel.bin";
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
let fails = 0, n = 0;
const ok = (what, c) => { console.log((c ? "ok   " : "FAIL ") + what); if (!c) fails++; };
const UA = {
  ios: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1",
  ios26: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
  sheet: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
  and: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
  awv: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP2A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.0.0 Mobile Safari/537.36",
  sam: "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/28.0 Chrome/130.0.0.0 Mobile Safari/537.36",
  desk: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
};
const forget = () => rmSync(STORE, { force: true });
function blank(x) {
  if (typeof x === "string") return x.length > 18 && x.includes(" ") ? PH : x;
  if (Array.isArray(x)) return x.map(blank);
  if (x && typeof x === "object") return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v)]));
  return x;
}
async function ctxFor(kind, { vp = null, dark = false } = {}) {
  const android = /Android/.test(UA[kind]), desk = kind === "desk";
  vp = vp || (desk ? { width: 1280, height: 800 } : android ? { width: 412, height: 915 } : { width: 390, height: 844 });
  return browser.newContext({ userAgent: UA[kind], viewport: vp, deviceScaleFactor: desk ? 1 : 2,
    isMobile: !desk, hasTouch: !desk, colorScheme: dark ? "dark" : "light", timezoneId: "America/Chicago" });
}
const hellos = [];
async function open(ctx, kind, { standalone = false, url = "/", wait = ".fn, [data-who]" } = {}) {
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); fails++; });
  if (kind === "ios") await p.addInitScript(() => { const s = CSS.supports.bind(CSS); CSS.supports = (...a) => /anchor-name/.test(a.join("")) ? false : s(...a); });
  if (standalone) await p.addInitScript(() => Object.defineProperty(navigator, "standalone", { get: () => true }));
  await p.addStyleTag({ content: "" }).catch(() => {});
  await p.route(SHIP + "/**", async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === "/api/hello") hellos.push(u.search);
    let r;
    try { r = await route.fetch({ url: SRV + u.pathname + u.search }); } catch { return; }
    if (u.pathname === "/text.json" || u.pathname === "/engage.json") {
      const j = await r.json();
      for (const k of ["cards", "epi", "reread", "notes", "reveal", "voice", "core", "drops", "jobs", "file", "patches"]) if (k in j) j[k] = blank(j[k]);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(j) });
    }
    await route.fulfill({ response: r });
  });
  await p.goto(SHIP + url);
  await p.addStyleTag({ content: ":root{--sb:34px}" });
  if (wait) await p.waitForSelector(wait);
  return p;
}
async function shot(p, name) {
  await p.waitForTimeout(150);
  const v = p.viewportSize(), dark = await p.evaluate(() => matchMedia("(prefers-color-scheme: dark)").matches);
  const f = `${out}/${name}-${dark ? "dark" : "light"}-${v.width}x${v.height}.png`;
  await p.screenshot({ path: f });
  console.log(f);
}
const h1 = (p) => p.$eval("#v h1", (e) => e.textContent).catch(() => "");
const scr = (p) => p.evaluate(() => FN.scr);
const fit = (p) => p.evaluate(() => document.documentElement.scrollWidth <= innerWidth && [...document.querySelectorAll(".fx *")].every((e) => e.getBoundingClientRect().right <= innerWidth + 0.5));
const next = (p) => p.click("[data-fn=next]");
// What the ship says about this phone, asked the way the page does.
const ship = async (ctx = "other") => (await (await fetch(SRV + "/api/hello?ctx=" + ctx)).json());

// 1. iOS: the captive sheet first. It only sends you to Safari, with the address.
forget();
for (const vp of [{ width: 390, height: 844 }, { width: 320, height: 640 }]) {
  const c = await ctxFor("sheet", { vp }); const p = await open(c, "sheet");
  ok(`iOS sheet ${vp.width}: route to Safari`, (await scr(p)) === "LEAVE" && /Open the game in Safari/.test(await h1(p)));
  const t = await p.$eval("#v", (e) => e.textContent);
  ok(`iOS sheet ${vp.width}: Cancel, Use Without Internet, the address`, /Cancel/.test(t) && /Use Without Internet/.test(t) && /192\.168\.4\.1/.test(t));
  ok(`iOS sheet ${vp.width}: no game, no way to play here`, !(await p.$("[data-who], [data-fn=here], [data-fn=play]")));
  ok(`iOS sheet ${vp.width}: fits the width`, await fit(p));
  await shot(p, "funnel-01-ios-captive-sheet");
  await c.close();
}
ok("the ship saw the sheet, nothing more", JSON.stringify(await ship()) === JSON.stringify({ installed: 0, tab: 0, sheet: 1, key: "ip" }));

// 2. iOS 26 Safari: the intro, then the illustrated steps.
for (const vp of [{ width: 390, height: 844 }, { width: 320, height: 640 }]) {
  const c = await ctxFor("ios26", { vp }); const p = await open(c, "ios26");
  ok(`iOS 26 ${vp.width}: first visit shows the guide's intro`, (await scr(p)) === "ADD" && /Get to Mars, together/.test(await h1(p)) && !!(await p.$(".fn .net")));
  ok(`iOS 26 ${vp.width}: the intro's Wi-Fi, Bluetooth and daily rows`, (await p.$$eval(".fn .bl b", (b) => b.map((x) => x.textContent))).join() === "Wi-Fi,Bluetooth,Daily,The icon");
  ok(`iOS 26 ${vp.width}: no marker on iOS`, !/src=icon/.test(p.url()));
  await shot(p, "funnel-02-ios26-guide-1-intro");
  const want = [["Open Share", /page menu|address bar/, 2], ["Add to Home Screen", /View More/, 2], ["Keep it a web app", /Open as Web App/, 2], ["Open it from the icon", /home screen/, 1]];
  for (let i = 0; i < want.length; i++) {
    await next(p);
    const [t, re, marks] = want[i];
    ok(`iOS 26 ${vp.width} step ${i + 2}: ${t}`, (await h1(p)).endsWith(t) && re.test(await p.$eval(".fn .lead", (e) => e.innerHTML + e.textContent)));
    ok(`iOS 26 ${vp.width} step ${i + 2}: ${marks} marked tap${marks > 1 ? "s" : ""} in the drawing`, (await p.$$(".fx .fnn")).length === marks);
    ok(`iOS 26 ${vp.width} step ${i + 2}: fits`, await fit(p));
    await shot(p, `funnel-0${i + 3}-ios26-guide-${i + 2}-${t.toLowerCase().replace(/ /g, "-")}`);
  }
  ok(`iOS 26 ${vp.width}: the last step offers play here, no Next`, !!(await p.$("#dock [data-fn=here]")) && !(await p.$("[data-fn=next]")));
  await p.click("[data-fn=back]");
  ok(`iOS 26 ${vp.width}: Back`, /Keep it a web app/.test(await h1(p)));
  await c.close();
}
// Dark, one card.
{ const c = await ctxFor("ios26", { dark: true }); const p = await open(c, "ios26"); await next(p); await next(p);
  await shot(p, "funnel-04-ios26-guide-3-add-to-home-screen"); await c.close(); }
ok("still not installed: only the icon marks it", (await ship()).installed === 0);

// 3. The icon: iOS runs it standalone. The game loads; the ship marks this phone.
{ const c = await ctxFor("sheet"); const p = await open(c, "sheet", { standalone: true, wait: "[data-who]" });
  ok("icon launch: straight to the game", (await scr(p)) === "" && !(await p.$(".fn")));
  await p.waitForTimeout(300);
  ok("icon launch: told the ship (ctx=standalone&m=icon)", hellos.some((q) => /ctx=standalone&m=icon/.test(q)));
  ok("icon launch: the ship has this phone installed", (await ship()).installed === 1);
  await shot(p, "funnel-08-ios-icon-launch-game");
  await c.close(); }

// 4. Safari again: you have the icon. Play here anyway, or the steps again.
for (const vp of [{ width: 390, height: 844 }, { width: 320, height: 640 }]) {
  const c = await ctxFor("ios26", { vp }); const p = await open(c, "ios26");
  ok(`Safari ${vp.width} after the icon: "You have the icon"`, (await scr(p)) === "OPEN" && /You have the icon/.test(await h1(p)));
  ok(`Safari ${vp.width}: Play here anyway, and No icon on this phone?`, !!(await p.$("#dock [data-fn=play]")) && /No icon on this phone\?/.test(await p.$eval("[data-fn=add]", (e) => e.textContent)));
  await shot(p, "funnel-09-ios26-installed-you-have-the-icon");
  if (vp.width === 390) {
    await p.click("[data-fn=add]");
    ok("No icon? goes to the first step", /Open Share/.test(await h1(p)));
    await p.click("[data-fn=here]");
    await p.waitForSelector("[data-who]");
    ok("Play here: the game", (await scr(p)) === "GAME");
    await p.reload(); await p.waitForSelector("[data-who]");
    ok("Play here: a reload stays in the game", !(await p.$(".fn")));
  }
  await c.close();
}
// The pop-up, for a phone that has the icon: use the icon.
{ const c = await ctxFor("sheet"); const p = await open(c, "sheet");
  ok("iOS sheet, installed phone: open the game from your icon", (await scr(p)) === "LEAVE_KNOWN" && /from your icon/.test(await h1(p)));
  await shot(p, "funnel-10-ios-captive-sheet-installed");
  await c.close(); }

// 5. Reset this ship forgets the phones: sign in, reset, and the guide is back.
{ const tok = (await (await fetch(SRV + "/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ crew: 1, pin: "1234" }) })).json()).token;
  const r = await fetch(SRV + "/api/reset", { method: "POST", headers: { "Content-Type": "application/json", "X-Crew-Token": tok }, body: JSON.stringify({ confirm: 3 }) });
  ok("reset: 200", r.status === 200);
  await new Promise((s) => setTimeout(s, 1500));
  ok("reset: the ship has forgotten this phone", JSON.stringify(await ship()) === JSON.stringify({ installed: 0, tab: 0, sheet: 0, key: "ip" }));
  const c = await ctxFor("ios26"); const p = await open(c, "ios26");
  ok("reset: Safari shows the guide again", (await scr(p)) === "ADD");
  await c.close(); }

// 6. iOS 18 Safari: Share in the toolbar.
forget();
{ const c = await ctxFor("ios"); const p = await open(c, "ios");
  await next(p);
  ok("iOS 18: Share at the bottom of Safari", /Open Share/.test(await h1(p)) && /bottom/.test(await p.$eval(".fn .lead", (e) => e.textContent)));
  await shot(p, "funnel-11-ios18-guide-2-share");
  await next(p); await next(p);
  ok("iOS 18: Add, no web-app switch", /Add it/.test(await h1(p)) && !(await p.$(".fx .tg")));
  await c.close(); }

// 7. Android: the sign-in window, then Chrome with the icon's marker on the address.
forget();
{ const c = await ctxFor("awv"); const p = await open(c, "awv");
  ok("Android sign-in window: route to Chrome", (await scr(p)) === "LEAVE" && /Open the game in Chrome/.test(await h1(p)) && !(await p.$("[data-fn=here]")));
  await shot(p, "funnel-12-android-sign-in-window");
  await c.close(); }
{ const c = await ctxFor("and"); let p = await open(c, "and");
  ok("Chrome: the guide", (await scr(p)) === "ADD");
  ok("Chrome: the address carries ?src=icon while the guide shows", new URL(p.url()).search === "?src=icon");
  await shot(p, "funnel-13-android-guide-1-intro");
  for (const [i, t] of [[2, "Open Chrome's menu"], [3, "Add the icon"], [4, "Open it from the icon"]]) {
    await next(p);
    ok(`Chrome step ${i}: ${t}`, (await h1(p)).endsWith(t) && await fit(p));
    await shot(p, `funnel-1${i + 2}-android-guide-${i}-${t.toLowerCase().replace(/[' ]/g, "-")}`);
  }
  await p.reload(); await p.waitForSelector(".fn");
  ok("Chrome: a reload of the marked address isn't a launch", (await scr(p)) === "ADD" && (await ship()).installed === 0);
  // The shortcut: a new tab at the marked address.
  const q = await c.newPage(); await q.close();
  p = await open(c, "and", { url: "/?src=icon", wait: "[data-who]" });
  await p.waitForTimeout(300);
  ok("Android icon launch: the game, and the ship marks the phone", (await scr(p)) === "" && (await ship()).installed === 1);
  ok("Android icon launch: the marker comes off the address", new URL(p.url()).search === "");
  await shot(p, "funnel-17-android-icon-launch-game");
  await p.reload(); await p.waitForSelector("[data-who]");
  ok("Android icon tab: a reload stays in the game", !(await p.$(".fn")));
  const t = await open(c, "and");
  ok("Chrome tab after the icon: You have the icon", (await scr(t)) === "OPEN");
  await shot(t, "funnel-18-android-installed-you-have-the-icon");
  await c.close(); }
{ const c = await ctxFor("awv"); const p = await open(c, "awv");
  ok("Android sign-in window, installed phone: use the icon", (await scr(p)) === "LEAVE_KNOWN");
  await c.close(); }

// 8. Samsung Internet: text steps; a computer: the game, no funnel.
forget();
{ const c = await ctxFor("sam"); const p = await open(c, "sam"); await next(p);
  ok("Samsung Internet: Add page to, Home screen", /Add page to/.test(await p.$eval("#v", (e) => e.textContent)));
  await c.close(); }
{ const c = await ctxFor("desk"); const p = await open(c, "desk", { wait: "[data-who]" });
  ok("a computer: the game, no funnel", !(await p.$(".fn")));
  await c.close(); }

await browser.close();
console.log(fails ? `funnel shots: ${fails} FAILED` : "funnel shots: all ok");
process.exit(fails ? 1 : 0);

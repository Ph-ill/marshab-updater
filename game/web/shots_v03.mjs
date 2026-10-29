// 0.2.7 / 0.3.x screens against the board's own server code (tests/phone_serve.py), story
// text swapped for placeholders. One scenario per run:
//   node web/shots_v03.mjs safe PORT OUTDIR      safe mode (phone_serve.py --safe)
//   node web/shots_v03.mjs live PORT OUTDIR      Hail, the radio check and its test (phone_serve.py --live)
//   node web/shots_v03.mjs live-off PORT OUTDIR  Hail paused after a fault (phone_serve.py --live --live-off)
// Exits non-zero if a step fails.
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const [what, port, out] = process.argv.slice(2);
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
let fails = 0, ua = 0;
const ok = (w, c, why) => { console.log((c ? "ok   " : "FAIL ") + w + (c || why === undefined ? "" : " (" + why + ")")); if (!c) fails++; };
const blank = (x) => typeof x === "string" ? (x.length > 18 && x.includes(" ") ? PH : x) : Array.isArray(x) ? x.map(blank)
  : x && typeof x === "object" ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v)])) : x;
async function page({ width = 390, height = 844 } = {}) {
  const ctx = await browser.newContext({ userAgent: `Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1 v03/${ua++}`,
    viewport: { width, height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: "light", timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); fails++; });
  await p.addInitScript(() => sessionStorage.setItem("lv.here", "1"));
  for (const [path, keys] of [["/text.json", ["cards", "epi", "reread", "notes", "reveal", "voice", "core", "patches"]], ["/engage.json", ["drops", "jobs", "file"]]]) {
    await p.route(`**${path}*`, async (route) => {
      const j = await (await route.fetch()).json();
      for (const k of keys) if (k in j) j[k] = blank(j[k]);
      if (j.cards) j.cards = j.cards.map((c) => ({ ...c, t: "Placeholder. " + PH, o: c.o.map((o) => ["Placeholder option", PH, ...o.slice(2)]) }));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(j) });
    });
  }
  await p.route("https://raw.githubusercontent.com/**", (r) => r.abort("internetdisconnected"));
  await p.goto(`http://localhost:${port}/`);
  await p.addStyleTag({ content: ":root{--sb:34px}" });
  return p;
}
async function pin(p, who = 0) {
  await p.waitForSelector("[data-who]");
  await p.click(`[data-who="${who}"]`);
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
}
async function signIn(p, who = 0) {
  await pin(p, who);
  await p.waitForSelector("#dock nav, .kick.big");
  if (await p.$(".kick.big")) { await p.click("#dock .btn"); await p.waitForSelector(".kick.big", { state: "detached" }); }
  if (await p.$(".tut")) { await p.click("[data-tut=skip]"); await p.waitForSelector(".tut", { state: "detached" }); }
  await p.waitForSelector("#dock nav");
}
async function shot(p, name) {
  await p.evaluate((ph) => { for (const li of document.querySelectorAll(".log li, .epi p")) li.textContent = ph; }, PH); await p.waitForTimeout(250); await p.screenshot({ path: `${out}/${name}.png` }); console.log("shot " + name); }
// Both phone widths: iPhone (390x844) and a common Android (412x915), the same page.
async function shot2(p, name, sel) {
  for (const [w, h, tag] of [[390, 844, "iphone-390"], [412, 915, "android-412"]]) {
    await p.setViewportSize({ width: w, height: h });
    if (sel) await p.$eval(sel, (e) => { e.scrollIntoView({ block: "start" }); scrollBy(0, -(document.querySelector("#top")?.offsetHeight || 0) - 12); });
    await shot(p, `${name}-${tag}`);
  }
  await p.setViewportSize({ width: 390, height: 844 });
}
async function homeCard(p) {
  await p.waitForSelector("#lv-home");
  return p.textContent("#lv-home");
}
const SCEN = {};
// Hail, state by state (phone_serve.py --live [--live-as=STATE]), at both widths
SCEN.hail = async () => {
  const p = await page();
  await signIn(p, 2);
  const t = await homeCard(p);
  ok("hail: Sending", /Sending/.test(t), t);
  ok("hail: Will deliver", /Will deliver/.test(t), t);
  ok("hail: Delivered", /Delivered/.test(t), t);
  ok("hail: X saw it", /saw it/.test(t), t);
  ok("hail: Hail back offered", /Hail back/.test(t), t);
  ok("hail: no light note by day", !(await p.$("#lv-home .lvrest")));
  await shot2(p, "hail-1-states", "#lv-home");
  await p.click("[data-lvbk]");
  await p.waitForSelector("[data-lvph]");
  ok("hail: Hail back picks them", (await p.getAttribute("[data-lvto='0']", "aria-pressed")) === "true");
  await shot2(p, "hail-2-hailback");
  await p.$eval("[data-lvto='6']", (e) => e.scrollIntoView({ block: "center" }));
  ok("hail: older ship gated", await p.$eval("[data-lvto='6']", (e) => e.disabled && /Needs the latest ship software/.test(e.textContent)));
  await shot2(p, "hail-3-older-ship-gated");
  await p.evaluate(() => go("crew/6"));
  await p.waitForSelector("#lv-crew");
  ok("hail: older ship's page says why", /needs the latest ship software/.test(await p.textContent("#lv-crew")));
  await shot2(p, "hail-4-older-ship-crew", "#lv-crew");
  await p.evaluate(() => go("hail"));
  await p.waitForSelector("[data-lvph]");
  await p.click("[data-lvto='3']");
  await p.click("[data-lvph='2']");
  await p.route("**/api/live/hail", async (r) => { await new Promise((f) => setTimeout(f, 2500)); await r.continue(); });
  await p.click("[data-lvsend]");
  await p.waitForFunction(() => /Sending/.test(document.querySelector("#dock").textContent));
  await shot2(p, "hail-5-sending");
  await p.waitForSelector("#lv-home", { timeout: 10000 });
  ok("hail: sent, on the home screen", /Coffee\?/.test(await p.textContent("#lv-home")));
};
SCEN["hail-idle"] = async () => {
  const p = await page();
  await signIn(p, 2);
  const t = await homeCard(p);
  ok("hail-idle: no hails yet", /Send a crewmate a few words/.test(t) && /20 left today/.test(t), t);
  await shot2(p, "hail-0-idle", "#lv-home");
};
SCEN["hail-night"] = async () => {
  const p = await page();
  await signIn(p, 2);
  const t = await homeCard(p);
  ok("hail-night: quiet hours said", /Quiet hours until 07:00/.test(t), t);
  await shot2(p, "hail-6-quiet-hours", "#lv-home");
  await p.click("#top .gear");   // Settings: the gear in the top bar
  await p.waitForSelector("#set-live [data-lvset]");
  ok("hail-night: settings too", /Quiet hours until 07:00/.test(await p.textContent("#set-live")));
  await shot2(p, "hail-6b-quiet-hours-settings", "#set-live");
};
SCEN["hail-cap"] = async () => {
  const p = await page();
  await signIn(p, 2);
  const t = await homeCard(p);
  ok("hail-cap: the day's lights used", /12 times today/.test(t), t);
  await shot2(p, "hail-7-cap-reached", "#lv-home");
  await p.click("#top .gear");   // Settings: the gear in the top bar
  await p.waitForSelector("#set-live [data-lvset]");
  ok("hail-cap: settings: 12 so far", /\(12 so far\)/.test(await p.textContent("#set-live")));
  await shot2(p, "hail-7b-cap-settings", "#set-live");
};
SCEN["hail-off"] = async () => {
  const p = await page();
  await signIn(p, 2);
  await p.waitForTimeout(800);
  ok("hail-off: no hail card", !(await p.$("#lv-home")));
  await p.click("#top .gear");   // Settings: the gear in the top bar
  await p.waitForSelector("#set-live [data-lvset=on]");
  ok("hail-off: switch says off", /Ship-to-ship: off/.test(await p.textContent("#set-live")));
  await shot2(p, "hail-8-off", "#set-live");
};
SCEN["hail-fleet"] = async () => {
  const p = await page();
  await signIn(p, 2);
  await p.waitForTimeout(800);
  ok("hail-fleet: no hail card", !(await p.$("#lv-home")));
  await p.click("#top .gear");   // Settings: the gear in the top bar
  await p.waitForSelector("#set-live .lvwhy");
  const t = await p.textContent("#set-live");
  ok("hail-fleet: paused for every ship, no switch", /paused on every ship/.test(t) && !(await p.$("#set-live [data-lvset]")), t);
  await shot2(p, "hail-9-fleet-kill-switch", "#set-live");
};
SCEN.safe = async () => {
  const p = await page();
  await p.waitForSelector("#safe-n");
  ok("safe: the sign-in says safe mode", /Safe mode/.test(await p.textContent("#safe-n")));
  await shot(p, "safe-1-signin");
  await pin(p);
  await p.waitForSelector("#safe-retry");
  const t = await p.textContent("#v");
  ok("safe: the screen", /Your ship is resting/.test(t) && /twice in a row/.test(t) && /Ship software/.test(t), t.slice(0, 200));
  ok("safe: no tabs", !(await p.$("#dock nav")));
  await shot(p, "safe-2-screen");
  await p.click("[data-safe=retry]");
  await p.waitForFunction(() => /Restarting/.test(document.querySelector("#dock").textContent));
  ok("safe: restarting", /Rejoin your ship/.test(await p.textContent("#v")));
  await shot(p, "safe-3-retry");
};
SCEN.live = async () => {
  const p = await page();
  await signIn(p, 2);
  await p.waitForSelector("#lv-home");
  let t = await p.textContent("#lv-home");
  ok("live: a hail on the home screen", /Hello from my ship/.test(t) && /Hail back/.test(t), t);
  ok("live: seen and waiting", /saw it/.test(t) && /Will deliver/.test(t), t);
  await shot(p, "live-1-home");
  await p.waitForTimeout(1600);
  const seen = await p.evaluate(async () => (await (await fetch("/api/live", { headers: { "X-Crew-Token": tok } })).json()).in[0].seen);
  ok("live: marked seen once shown", seen === 1, seen);
  await p.click("[data-lvbk]");
  await p.waitForSelector("[data-lvph]");
  ok("live: hail back picks them", (await p.getAttribute("[data-lvto='0']", "aria-pressed")) === "true");
  ok("live: old ship can't be picked", await p.$eval("[data-lvto='6']", (e) => e.disabled));
  ok("live: send waits for words", await p.$eval("[data-lvsend]", (e) => e.disabled));
  await p.click("[data-lvph='7']");
  await shot(p, "live-2-hailback");
  await p.click("[data-lvsend]");
  await p.waitForSelector("#lv-home");
  t = await p.textContent("#lv-home");
  ok("live: sent, back home", /Heading out/.test(t), t);
  await shot(p, "live-3-sent");
  await p.click("[data-go=hail]");
  await p.waitForSelector("[data-lvph]");
  // Fair use: one hail on its way per crewmate. The page won't pick them, and says why...
  ok("live: fair use, can't pick them again", await p.$eval("[data-lvto='0']", (e) => e.disabled && /on its way/.test(e.textContent)));
  // ...and the ship says no too (a stale page, or another phone).
  const st = await p.evaluate(async () => (await fetch("/api/live/hail", { method: "POST", headers: { "X-Crew-Token": tok }, body: JSON.stringify({ to: 0, ph: 1 }) })).status);
  ok("live: fair use, the ship refuses", st === 429, st);
  await shot(p, "live-4-fairuse");
  await p.click("[data-go=home]").catch(() => {});
  await p.evaluate(() => go("crew/1"));
  await p.waitForSelector("#lv-crew");
  ok("live: crewmate page", /Hail/.test(await p.textContent("#lv-crew")));
  await shot(p, "live-5-crewmate");
  await p.evaluate(() => go("set"));
  await p.waitForSelector("#set-live [data-lvset]");
  await p.$eval("#set-live", (e) => e.scrollIntoView());
  ok("live: settings section", /Hail light/.test(await p.textContent("#set-live")));
  await shot(p, "live-6-settings");
  await p.click("[data-go=coex]");
  await p.waitForSelector("#v dl.facts");
  ok("live: radio check", /Ships heard/.test(await p.textContent("#v")));
  await shot(p, "live-7-radio");
  await p.click("[data-lvtest]");
  await p.waitForSelector("#lv-test dl.facts");
  await shot(p, "live-7b-testing");
  await p.waitForSelector("[data-lvtest]", { timeout: 60000 });
  t = await p.textContent("#lv-test");
  ok("live: radio test answered", /Answered\s*30 of 30/.test(t) && /KB\/s/.test(t) && /Meanwhile/.test(t), t);
  await p.$eval("#lv-test", (e) => e.scrollIntoView());
  await shot(p, "live-7c-tested");
};
SCEN["live-off"] = async () => {
  const p = await page();
  await signIn(p, 2);
  await p.waitForSelector("#v .kick");
  ok("live-off: no hail card", !(await p.$("#lv-home")));
  await p.evaluate(() => go("set"));
  await p.waitForSelector("#set-live [data-lvset=on]");
  await p.$eval("#set-live", (e) => e.scrollIntoView());
  ok("live-off: says why", /Paused on its own/.test(await p.textContent("#set-live")));
  await shot(p, "live-8-paused");
  await p.click("[data-lvset=on]");
  await p.waitForSelector("#set-live [data-lvset=off]");
  ok("live-off: back on", /Ship-to-ship: on/.test(await p.textContent("#set-live")));
  await shot(p, "live-9-backon");
};
if (globalThis.EXTRA) Object.assign(SCEN, globalThis.EXTRA);
try { await SCEN[what](); } catch (e) { console.error(e); fails++; }
await browser.close();
console.log(fails ? `${fails} failed` : "all ok");
process.exit(fails ? 1 : 0);

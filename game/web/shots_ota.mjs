// Over-the-air update screens (web/ota.js), clicked through against the mock Pico (sim/mockota.py):
// the home-screen notice, the gear's update dot, Settings' Ship software section, installing,
// installed, an update that went back, and a check with no internet. GitHub is stood in for by
// the mock's /gh/ (a release signed with the TEST key, filler files). Every story line on
// screen is swapped for placeholder text, as in shots_you.mjs. Exits non-zero if a step fails.
//   game/web/shots_ota.sh OUTDIR   (starts mocks on 8056 ota=0.2.0 and 8057 ota=0.2.0,back)
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
const GH = "https://raw.githubusercontent.com/Ph-ill/marshab-updater/main/";
let ua = 0, fails = 0;
const ok = (what, c) => { console.log((c ? "ok   " : "FAIL ") + what); if (!c) fails++; };

function blank(x) {
  if (typeof x === "string") return x.length > 18 && x.includes(" ") ? PH : x;
  if (Array.isArray(x)) return x.map(blank);
  if (x && typeof x === "object") return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v)]));
  return x;
}
async function page(port, { online = true } = {}) {
  const ctx = await browser.newContext({ userAgent: `Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1 ota/${ua++}`,
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: "light", timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); fails++; });
  // Past the install guide (web/funnel.js), as after "Play in this browser this time".
  await p.addInitScript(() => sessionStorage.setItem("lv.here", "1"));
  for (const [path, keys] of [["/text.json", ["cards", "epi", "reread", "notes", "reveal", "voice", "core"]], ["/engage.json", ["drops", "jobs", "file"]]]) {
    await p.route(`**${path}*`, async (route) => {
      const j = await (await route.fetch()).json();
      for (const k of keys) if (k in j) j[k] = blank(j[k]);
      if (j.cards) j.cards = j.cards.map((c) => ({ ...c, t: "Placeholder. " + PH, o: c.o.map((o) => ["Placeholder option", PH, ...o.slice(2)]) }));
      if (j.crew) j.habit = undefined;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(j) });
    });
  }
  await p.route(GH + "**", async (route) => {
    if (!online) return route.abort("internetdisconnected");
    const r = await route.fetch({ url: `http://localhost:${port}/gh/` + route.request().url().slice(GH.length) });
    await route.fulfill({ response: r });
  });
  await p.goto(`http://localhost:${port}/?day=22`);
  await p.addStyleTag({ content: ":root{--sb:34px}" });
  await p.waitForSelector("[data-who]");
  await p.click('[data-who="0"]');
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector("#dock nav, .kick.big");
  if (await p.$(".kick.big")) { await p.click("#dock .btn"); await p.waitForSelector(".kick.big", { state: "detached" }); }
  if (await p.$(".tut")) { await p.click("[data-tut=skip]"); await p.waitForSelector(".tut", { state: "detached" }); }
  await p.waitForSelector("#dock nav");
  return p;
}
async function shot(p, name) {
  await p.evaluate((ph) => { for (const li of document.querySelectorAll(".log li, .epi p")) li.textContent = ph; }, PH);
  await p.waitForTimeout(150);
  const f = `${out}/${name}-light-390x844.png`;
  await p.screenshot({ path: f });
  console.log(f);
}
const goto = (p, r) => p.evaluate((r) => go(r), r);

// 1. A good update: notice, row, screen, install, installed.
let p = await page(8056);
await p.waitForSelector(".otab", { timeout: 15000 });
ok("home shows the update notice", await p.$eval(".otab", (e) => e.textContent.includes("0.2.1")));
await shot(p, "ota-01-home-update-ready");
await p.click("[data-ota=later]");
ok("Later hides the notice", !(await p.$(".otab")));
ok("the gear shows the update dot", await p.$eval("#top .gear", (e) => e.classList.contains("dot") && e.getAttribute("aria-label") === "Settings, update ready"));
await goto(p, "crew");
ok("your crew page has no Ship software row", !(await p.$("#v [data-go=sw], #v [data-ota]")));
await shot(p, "ota-02-gear-update-dot");
await p.click("#top .gear");
ok("the gear opens Settings", await p.evaluate(() => route === "set") && await p.$eval("#v h1", (e) => e.textContent === "Settings"));
ok("Settings' Ship software says update ready", await p.$eval("#set-sw", (e) => e.textContent.includes("update ready") && e.textContent.includes("0.2.1")));
await p.waitForSelector("[data-ota=install]");
await shot(p, "ota-03-settings-ship-software-update-ready");
await goto(p, "home");
await p.evaluate(() => { OTA_LATER = ""; view(); });
await p.click(".otab [data-ota=install]");
ok("the notice's Install opens Settings", await p.evaluate(() => route === "set"));
await p.waitForFunction(() => OI && OI.step === "send" && OI.f >= 4);
await shot(p, "ota-04-installing");
await p.waitForSelector("[data-ota=reload]", { timeout: 60000 });
ok("installed: the ship runs 0.2.1", await p.$eval("#v", (e) => e.textContent.includes("runs 0.2.1 now")));
await shot(p, "ota-05-installed");
await p.click("[data-ota=reload]");
await p.waitForSelector("[data-who]");
const st = await p.evaluate(async () => (await fetch("/api/ota")).json());
ok("after the reload the ship reports 0.2.1, installed", st.v === "0.2.1" && st.last && st.last.result === "installed");
await p.context().close();

// 2. An update that doesn't start: the ship goes back by itself.
p = await page(8057);
await goto(p, "sw");
ok("the old #sw route lands in Settings", await p.evaluate(() => route === "set" && location.hash === "#set"));
await p.waitForSelector("[data-ota=install]", { timeout: 15000 });
await p.click("[data-ota=install]");
await p.waitForSelector("[data-ota=clear]", { timeout: 60000 });
ok("rolled back: says so", await p.$eval("#v", (e) => e.textContent.includes("went back to 0.2.0")));
await shot(p, "ota-06-went-back");
await p.click("[data-ota=clear]");
ok("Settings shows the rollback", await p.$eval("#set-sw", (e) => e.textContent.includes("didn't start")));
await shot(p, "ota-07-ship-software-after-rollback");
await p.context().close();

// 3. On the ship's hotspot with no internet: the check fails quietly; the screen says what to do.
p = await page(8056, { online: false });
await p.waitForTimeout(1500);
ok("no internet: no notice, no error", !(await p.$(".otab")) && !(await p.$(".off")));
await goto(p, "set");
await p.click("[data-ota=check]");
await p.waitForFunction(() => document.querySelector("#v").textContent.includes("no internet"));
ok("Check for updates with no internet says so", true);
await shot(p, "ota-08-check-no-internet");
await p.context().close();
await browser.close();
console.log(fails ? `FAIL ${fails}` : "ota shots: all ok");
process.exit(fails ? 1 : 0);

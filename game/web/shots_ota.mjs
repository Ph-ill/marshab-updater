// Over-the-air update screens (web/ota.js), clicked through against the mock Pico (sim/mockota.py):
// the home-screen notice, the gear's update dot, Settings' Ship software section, installing,
// installed, an update that went back, and a check with no internet. GitHub is stood in for by
// the mock's /gh/ (a release signed with the TEST key, filler files). Every story line on
// screen is swapped for placeholder text, as in shots_you.mjs. Exits non-zero if a step fails.
//   game/web/shots_ota.sh OUTDIR   (starts mocks on 8056 ota=0.2.0, 8057 ota=0.2.0,back,
//   and 8066 ota=0.2.0 for what's new, section 5)
import { createRequire } from "module";
import { readFileSync } from "fs";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
const GH = "https://raw.githubusercontent.com/Ph-ill/marshab-updater/main/";
let ua = 0, fails = 0;
const ok = (what, c, why) => { console.log((c ? "ok   " : "FAIL ") + what + (!c && why ? "\n       " + why : "")); if (!c) fails++; };

function blank(x) {
  if (typeof x === "string") return x.length > 18 && x.includes(" ") ? PH : x;
  if (Array.isArray(x)) return x.map(blank);
  if (x && typeof x === "object") return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v)]));
  return x;
}
const GHB = "https://raw.githubusercontent.com/Ph-ill/marshab-updater/";
const IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36";
// idx: changes GitHub's index.json on its way to the phone (section 5's notes with markup in).
async function page(port, { online = true, src = null, asked = null, w = 390, ht = 844, android = false, idx = null } = {}) {
  const ctx = await browser.newContext({ userAgent: `${android ? ANDROID : IOS} ota/${ua++}`,
    viewport: { width: w, height: ht }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: "light", timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("console", (m) => { if (m.text().startsWith("stage:")) console.log(m.text()); });
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
  // GitHub: main, or (a ship whose ship.json has ota_src) that branch; every URL asked for is noted
  const gh = src ? GHB + src + "/" : GH;
  await p.route(GHB + "**", async (route) => {
    const u = route.request().url();
    if (asked) asked.push(u);
    if (!online) return route.abort("internetdisconnected");
    if (!u.startsWith(gh)) return route.fulfill({ status: 404, body: "" });
    const r = await route.fetch({ url: `http://localhost:${port}/gh/` + u.slice(gh.length) });
    if (idx && route.request().url().endsWith("index.json")) return route.fulfill({ response: r, json: idx(await r.json()) });
    await route.fulfill({ response: r });
  });
  if (src) await p.route(/\/api\/ota$/, async (route) => {
    const r = await route.fetch();
    const j = await r.json();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...j, src }) });
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
async function shot(p, name, { full = false } = {}) {
  await p.evaluate((ph) => { for (const li of document.querySelectorAll(".log li, .epi p")) li.textContent = ph; }, PH);
  await p.waitForTimeout(150);
  const v = p.viewportSize(), f = `${out}/${name}-light-${v.width}x${v.height}.png`;
  await p.screenshot({ path: f, fullPage: full });
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
await p.waitForFunction(() => document.querySelector("#v").textContent.includes("couldn't reach GitHub"));
ok("Check for updates with no internet explains the network failure", true);
await shot(p, "ota-08-check-no-internet");
ok("no internet: Available says it couldn't check", await p.$eval("#set-sw", (e) => /Available\s*Couldn't check/.test(e.textContent) && !e.textContent.includes("Up to date")));
await p.context().close();

// 3b. (Phill's iPhone) This phone once looked and saw the version the ship runs ("Up to
// date"), then the latest check fails: Available must not still say "Up to date".
p = await page(8056, { online: false });
await p.waitForTimeout(1500);
await goto(p, "set");
await p.evaluate(() => { const b = otaLoad(); b.seen = OS_.v; b.ok = true; b.err = ""; b.at = Date.now() - 7 * 3600e3; otaSave(b); OB = b; view(); });
ok("an earlier good look: Up to date", await p.$eval("#set-sw", (e) => /Available\s*Up to date/.test(e.textContent)));
await p.click("[data-ota=check]");
await p.waitForFunction(() => document.querySelector("#v").textContent.includes("couldn't reach GitHub"));
ok("then a failed check: Couldn't check, not Up to date, with network steps", await p.$eval("#set-sw", (e) => /Available\s*Couldn't check/.test(e.textContent) && !e.textContent.includes("Up to date") && /Checked\s*just now/.test(e.textContent) && e.textContent.includes("Turn Wi-Fi off") && e.textContent.includes("storage is separate")));
await shot(p, "ota-09-failed-check-after-up-to-date");
await p.context().close();

// 4. A test ship reading a test branch (ship.json "ota_src"): the page fetches from that
// branch of the repo, never main, and offers what's there.
const asked = [];
// (8056 runs 0.2.1 by now and 8057 went back from it: look at what the phone fetched)
p = await page(8057, { src: "ota-phonetest", asked });
await p.waitForFunction(() => { const b = JSON.parse(localStorage.getItem("lv.ota") || "{}"); return b.rel && b.rel.v; }, null, { timeout: 15000 });
ok("test branch: the release fetched from the branch", await p.evaluate(() => {
  const b = JSON.parse(localStorage.getItem("lv.ota")); return b.src === "ota-phonetest" && b.rel.v === "0.2.1"; }));
ok("test branch: index and release from ota-phonetest only", asked.length >= 2
   && asked.every((u) => u.startsWith(GHB + "ota-phonetest/firmware/")) && asked.some((u) => u.endsWith("/firmware/index.json")));
await p.context().close();

// 5. Carrying on with an upload that was cut short (0.3.0, review R2): only when the ship
// staged this very envelope (the same sha256); anything else is cancelled and sent again
// from nothing, and so is a resume the ship turns down with a checksum error (400). On the
// ",back" mock, which stays on 0.2.0, so the same update can be offered again and again.
async function stage(p, { env2 = false, files = 1, part = 0 } = {}) {
  return p.evaluate(async ({ env2, files, part }) => {
    const r = otaFor(OS_ || await otaStatus());
    let e = r.env;
    if (env2) { const j = JSON.parse(e); j.sig = (j.sig[0] === "A" ? "B" : "A") + j.sig.slice(1); e = JSON.stringify(j); }
    const put = async (q, b) => (await fetch("/api/ota/put?" + q, { method: "POST", body: b, headers: { "X-Crew-Token": tok } })).status;
    const env = new TextEncoder().encode(e);
    for (let o = 0; o < env.length; o += 1024) await put(`f=0&n=${env.length}&o=${o}`, env.subarray(o, o + 1024));
    for (let i = 0; i < files; i++) {
      const b = Uint8Array.from(atob(r.files[i]), (c) => c.charCodeAt(0));
      for (let o = 0; o < b.length; o += 1024) await put(`f=${i + 1}&o=${o}`, b.subarray(o, o + 1024));
    }
    if (part) { const b = Uint8Array.from(atob(r.files[files]), (c) => c.charCodeAt(0)); await put(`f=${files + 1}&o=0`, b.subarray(0, part)); }
    const st = await (await fetch("/api/ota")).json();
    if (!st.staged) console.log("stage: " + JSON.stringify({ st, n: env.length, tok: !!tok }));
    return st.staged;
  }, { env2, files, part });
}
async function install(p) {
  const log = [];
  const on = (r) => { const u = r.url(); if (r.method() === "POST" && u.includes("/api/ota/")) log.push(u.replace(/^.*\/api\/ota\//, "")); };
  p.on("request", on);
  await p.evaluate(() => { otaInstall(); });
  await p.waitForSelector("[data-ota=clear]", { timeout: 60000 });
  p.off("request", on);
  return log;
}
p = await page(8057);
await p.waitForTimeout(1200);
let sg = await stage(p, { files: 2 });
ok("R2: the ship reports the staged envelope's hash", sg && /^[0-9a-f]{64}$/.test(sg.h) && await p.evaluate((h) => h === otaSha(new TextEncoder().encode(otaFor(OS_).env)), sg.h));
let log = await install(p);
ok("R2: same envelope: carries on, no cancel, the signature and the done files not sent again",
  !log.includes("cancel") && !log.some((x) => x.startsWith("put?f=0&")) && !log.some((x) => /^put\?f=[12]&/.test(x)) && log.some((x) => x.startsWith("put?f=3&")) && log.includes("apply"), log.join(" "));
await p.context().close();
await new Promise((r) => setTimeout(r, 6500));   // a restart signs everyone out: a fresh page
p = await page(8057); await p.waitForTimeout(1200);
sg = await stage(p, { env2: true, files: 2 });
ok("R2: a version signed twice stages a different hash", sg && sg.h !== await p.evaluate(() => otaSha(new TextEncoder().encode(otaFor(OS_).env))), JSON.stringify(sg));
log = await install(p);
const c = log.indexOf("cancel"), e0 = log.findIndex((x) => x.startsWith("put?f=0&") && x.endsWith("&o=0"));
ok("R2: a different envelope: cancelled, then everything from offset 0", c === 0 && e0 === 1 && log.some((x) => x === "put?f=1&o=0") && log.includes("apply"), log.join(" "));
await p.context().close();
await new Promise((r) => setTimeout(r, 6500));
p = await page(8057); await p.waitForTimeout(1200);
sg = await stage(p, { files: 1, part: 1024 });
await p.evaluate(async () => fetch("/api/ota/mockbad?f=2", { method: "POST", headers: { "X-Crew-Token": tok } }));
log = await install(p);
const b4 = log.findIndex((x) => x.startsWith("put?f=2&")), c2 = log.indexOf("cancel");
ok("R2: a 400 while carrying on: cancelled and sent again from the signature",
  b4 >= 0 && c2 > b4 && log[c2 + 1] && log[c2 + 1].startsWith("put?f=0&") && log[c2 + 1].endsWith("&o=0") && log.slice(c2).includes("put?f=1&o=0") && log.includes("apply"), log.join(" "));
ok("R2: the outcome is the ship's (went back), not an error", await p.$eval("#v", (e) => e.textContent.includes("went back to 0.2.0")));
await p.context().close();

// 5. What's new (0.3.0, group G), on an iPhone (390) and an Android phone (412): the ready
// update's few lines in Settings, before Install; Version history online (GitHub's index.json,
// newest first, the installed one and the ready one marked) and offline (the ship's own lines
// from GET /api/ota/notes, and how to see the rest); Back to Settings.
for (const [w, ht, android] of [[390, 844, false], [412, 915, true]]) {
  p = await page(8066, { w, ht, android });
  await goto(p, "set");
  await p.waitForSelector("#set-sw .otaw li", { timeout: 15000 });
  const wn = await p.$$eval("#set-sw .otaw li", (l) => l.map((x) => x.textContent));
  ok(`${w}: Settings shows the ready update's what's new, before Install`, wn.length === 3 && wn[0].startsWith("Hail a crewmate") &&
    await p.evaluate(() => !!(document.querySelector("#set-sw .otawn").compareDocumentPosition(document.querySelector("#set-sw [data-ota=install]")) & Node.DOCUMENT_POSITION_FOLLOWING)), wn.join(" | "));
  await p.evaluate(() => scrollTo(0, document.querySelector("#set-sw").offsetTop - 60));
  await shot(p, "whatsnew-01-settings-update-ready");
  await p.click("[data-ota=hist]");
  await p.waitForSelector(".otahv");
  const rows = await p.$$eval(".otahv", (l) => l.map((x) => [...x.querySelectorAll(".lab span")].map((s) => s.textContent)));
  ok(`${w}: history online: newest first, installed and ready marked`, JSON.stringify(rows.map((r) => r[0])) === '["0.2.1","0.2.0","0.1.9","0.1.8"]' &&
    rows[0][1] === "Ready to install" && rows[1][1] === "Installed" && rows[2][1] === "Oct 21" && await p.$$eval(".otahv.on", (l) => l.length === 1), JSON.stringify(rows));
  ok(`${w}: history online: each version's lines, no offline note`, await p.$$eval(".otahv .otaw li", (l) => l.length === 7) && !(await p.$(".otahc")));
  await p.evaluate(() => scrollTo(0, 0));
  await shot(p, "whatsnew-02-history-online");
  await shot(p, "whatsnew-02-history-online-full", { full: true });
  await p.click("[data-ota=back]");
  ok(`${w}: Back returns to Settings, on Version history`, await p.$eval("#v h1", (e) => e.textContent === "Settings") && await p.evaluate(() => document.activeElement && document.activeElement.dataset.ota === "hist"));
  await p.context().close();
  p = await page(8066, { w, ht, android, online: false });
  await goto(p, "set");
  // Offline the lines come from the page itself (web/build.py bakes whatsnew.json into
  // OTA_WN); the mock's "0.2.0" isn't a real version, so it borrows 0.2.7-ota-phone's.
  const WN = JSON.parse(readFileSync(new URL("../tools/ota/whatsnew.json", import.meta.url), "utf8"));
  ok(`${w}: the page carries whatsnew.json`, await p.evaluate((wn) => JSON.stringify(OTA_WN["0.3.0-ota-phone"]) === JSON.stringify(wn["0.3.0-ota-phone"]) && !("_about" in OTA_WN), WN));
  const asked = [];
  p.on("request", (r) => { if (r.url().includes("/api/ota/")) asked.push(r.url()); });
  await p.evaluate((n) => { OTA_WN["0.2.0"] = n; }, WN["0.2.7-ota-phone"]);
  await p.click("[data-ota=hist]");
  await p.waitForSelector(".otahc", { timeout: 15000 });
  const off = await p.$$eval(".otahv", (l) => l.map((x) => x.textContent));
  ok(`${w}: history offline: installed notes remain with guidance for older versions`, off.length === 1 && off[0].includes("0.2.0") && off[0].includes("Installed") && off[0].includes("simple safe mode") &&
    await p.$eval(".otahc", (e) => e.textContent.includes("couldn't reach GitHub") && e.textContent.includes("Older versions are listed online") && e.textContent.includes("To see them, check again on mobile data or another Wi-Fi network")), off.join(" | "));
  ok(`${w}: history offline: no /api/ota/ request for it`, asked.length === 0, asked.join(" "));
  await shot(p, "whatsnew-03-history-offline");
  await p.context().close();
}
// What's new is text: markup in index.json's notes shows as typed, never runs; at most 3 lines
// of 160 characters; anything not a string is dropped.
p = await page(8066, { idx: (j) => { j.releases[0].notes = ["<b>bold</b> & <img src=x onerror=\"window.PWN=1\">", 7, "x".repeat(500), "four", "five"]; return j; } });
await goto(p, "set");
await p.waitForSelector("#set-sw .otaw li", { timeout: 15000 });
const li = await p.$$eval("#set-sw .otaw li", (l) => l.map((x) => [x.textContent, x.children.length]));
ok("notes are text: no markup made, no script run", li[0][0] === '<b>bold</b> & <img src=x onerror="window.PWN=1">' && li[0][1] === 0 && !(await p.$("#set-sw .otaw b, #set-sw .otaw img")) && await p.evaluate(() => window.PWN === undefined), JSON.stringify(li));
ok("notes capped: 3 strings, 160 characters each", li.length === 3 && li[1][0] === "x".repeat(160) && li[2][0] === "four", JSON.stringify(li.map((x) => x[0].length)));
await p.context().close();
await browser.close();
console.log(fails ? `FAIL ${fails}` : "ota shots: all ok");
process.exit(fails ? 1 : 0);

// Screenshots of every screen in a chrome-less viewport (like the captive-portal sheet).
//   (shots.sh starts the mock Picos: 8042 for the signed-in screens, 8043-8047 fresh for onboarding;
//    every crew code is 1234 and Dorian is "not set up")
//   PW=/path/to/node_modules/playwright-core CHROME=/usr/bin/google-chrome node web/shots.mjs OUTDIR
// SIZES=cna picks the captive-sheet viewports below and writes OUTDIR/cna-WxH/NAME.png instead.
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const FULL = [
  { tag: "390x844", width: 390, height: 844, inset: "34px" },  // iPhone 12-15: home indicator
  { tag: "360x800", width: 360, height: 800, inset: "0px" },   // common Android
];
// What the page actually gets inside the captive-portal sheet (CSS px, estimates; see README).
const CNA = [
  { tag: "320x480", width: 320, height: 480, inset: "0px" },   // iPhone SE 2/3 with Display Zoom: worst case
  { tag: "375x580", width: 375, height: 580, inset: "0px" },   // iPhone SE 2/3 (667 tall), sheet + 56 px bar
  { tag: "375x700", width: 375, height: 700, inset: "34px" },  // iPhone 12/13 mini (812 tall)
  { tag: "390x730", width: 390, height: 730, inset: "34px" },  // iPhone 12-16 (844 tall)
  { tag: "360x600", width: 360, height: 600, inset: "0px" },   // Android sign-in tab under its two bars
];
const cna = process.env.SIZES === "cna";
const SIZES = cna ? CNA : FULL;
import { mkdirSync } from "fs";
if (cna) for (const s of CNA) mkdirSync(`${out}/cna-${s.tag}`, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME });

let ua = 0;  // a distinct User-Agent per context, so the ship doesn't "remember" an earlier one
async function page(size) {
  const ctx = await browser.newContext({ userAgent: `Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 shot/${ua++}`, viewport: { width: size.width, height: size.height }, deviceScaleFactor: 2,
    isMobile: true, hasTouch: true, colorScheme: "light" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); process.exitCode = 1; });
  return p;
}
async function inset(p, size) { await p.addStyleTag({ content: `:root{--sb:${size.inset}}` }); }
async function shot(p, size, name, full = false) {
  if (full) await p.addStyleTag({ content: "#dock{position:static}main{padding-bottom:0!important}" });
  await p.waitForTimeout(150);
  const f = cna ? `${out}/cna-${size.tag}/${name}.png` : `${out}/${name}-${size.tag}.png`;
  await p.screenshot({ path: f, fullPage: full });
  console.log(f);
}
async function signIn(p, size, day) {
  await p.goto(`http://localhost:8042/?day=${day}`);
  await inset(p, size);
  await p.click('[data-who="0"]');
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector("#dock nav, .tbl, .big");
  if (await p.$(".big")) { await p.click('[data-go="home"]'); await p.waitForSelector("#dock nav, .tbl"); }
}
const goto = (p, r) => p.evaluate((r) => go(r), r);

for (const [n, size] of SIZES.entries()) {
  let p = await page(size);
  await p.goto(`http://localhost:${8043 + n}/?day=8`);  // a fresh mock per size: nobody signed up yet
  await inset(p, size);
  await p.waitForSelector("[data-who]");
  await shot(p, size, "01-onboard-name");
  await p.click('[data-who="1"]');
  for (const k of "0000") await p.click(`[data-key="${k}"]`);
  await p.waitForFunction(() => document.querySelector(".err").textContent.includes("4 tries"));
  for (const k of "12") await p.click(`[data-key="${k}"]`);
  await shot(p, size, "02-onboard-code");
  for (const k of ["DEL", "DEL"]) await p.click(`[data-key="${k}"]`);
  for (const want of ["3 tries", "2 tries", "1 try", "Too many"]) {
    for (const k of "0000") await p.click(`[data-key="${k}"]`);
    await p.waitForFunction((w) => document.querySelector(".err").textContent.includes(w), want);
  }
  await shot(p, size, "12-locked");
  await p.click('[data-key="BACK"]');
  await p.click('[data-who="0"]');
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector(".big");
  await shot(p, size, "03-onboard-meet");
  await p.context().close();

  p = await page(size);
  await signIn(p, size, 8);
  await shot(p, size, "04-home");
  if (size.width === 390 && !cna) await shot(p, size, "04-home-full", true);
  await goto(p, "crew");
  await shot(p, size, "05-astronaut");
  if (size.width === 390 && !cna) await shot(p, size, "05-astronaut-full", true);
  await goto(p, "act");
  await p.click('[data-act="0"]');
  await p.click('[data-sub="t:2"]');
  await shot(p, size, "06-instruct");
  await goto(p, "item/5");
  await shot(p, size, "08-dilemma");
  await p.context().close();

  p = await page(size);
  await signIn(p, size, 7);
  await goto(p, "item/0");
  await p.click('[data-pick="0:0"]');
  await shot(p, size, "07-vote");
  await p.context().close();

  p = await page(size);
  await signIn(p, size, 11);
  await goto(p, "item/4");
  await shot(p, size, "09-rescue");
  await p.context().close();

  p = await page(size);
  await signIn(p, size, 23);
  await goto(p, "log");
  await shot(p, size, "10-log-top");   // today and yesterday: "may still change"
  await p.evaluate(() => document.getElementById("d21").scrollIntoView());
  await p.evaluate(() => scrollBy(0, -56));
  await shot(p, size, "10-log");
  await p.context().close();

  p = await page(size);
  await signIn(p, size, 42);
  await shot(p, size, "11-ending");
  if (size.width === 390 && !cna) await shot(p, size, "11-ending-full", true);
  await p.context().close();
}
await browser.close();

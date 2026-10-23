// Screenshots of every screen in a chrome-less viewport (like the captive-portal sheet).
//   python3 sim/mockserver.py --port 8042 claim=0:1234 &   python3 sim/mockserver.py --port 8043 &  (and 8044)
//   PW=/path/to/node_modules/playwright-core CHROME=/usr/bin/google-chrome node web/shots.mjs OUTDIR
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const SIZES = [
  { tag: "390x844", width: 390, height: 844, inset: "34px" },  // iPhone 12-15: home indicator
  { tag: "360x800", width: 360, height: 800, inset: "0px" },   // common Android
];
const browser = await chromium.launch({ executablePath: process.env.CHROME });

async function page(size) {
  const ctx = await browser.newContext({ viewport: { width: size.width, height: size.height }, deviceScaleFactor: 2,
    isMobile: true, hasTouch: true, colorScheme: "light" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); process.exitCode = 1; });
  return p;
}
async function inset(p, size) { await p.addStyleTag({ content: `:root{--sb:${size.inset}}` }); }
async function shot(p, size, name, full = false) {
  if (full) await p.addStyleTag({ content: "#dock{position:static}main{padding-bottom:0!important}" });
  await p.waitForTimeout(150);
  const f = `${out}/${name}-${size.tag}.png`;
  await p.screenshot({ path: f, fullPage: full });
  console.log(f);
}
async function signIn(p, size, day) {
  await p.goto(`http://localhost:8042/?day=${day}`);
  await inset(p, size);
  await p.click('[data-who="0"]');
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector("#dock nav, .tbl");
}
const goto = (p, r) => p.evaluate((r) => go(r), r);

for (const [n, size] of SIZES.entries()) {
  let p = await page(size);
  await p.goto(`http://localhost:${8043 + n}/?day=8`);  // a fresh mock per size: nobody signed up yet
  await inset(p, size);
  await p.waitForSelector("[data-who]");
  await shot(p, size, "01-onboard-name");
  await p.click('[data-who="0"]');
  for (const k of "47") await p.click(`[data-key="${k}"]`);
  await shot(p, size, "02-onboard-code");
  for (const k of "11") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector(".big");
  await shot(p, size, "03-onboard-meet");
  await p.context().close();

  p = await page(size);
  await signIn(p, size, 8);
  await shot(p, size, "04-home");
  if (size.width === 390) await shot(p, size, "04-home-full", true);
  await goto(p, "crew");
  await shot(p, size, "05-astronaut");
  if (size.width === 390) await shot(p, size, "05-astronaut-full", true);
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
  await p.evaluate(() => document.getElementById("d21").scrollIntoView());
  await p.evaluate(() => scrollBy(0, -56));
  await shot(p, size, "10-log");
  await p.context().close();

  p = await page(size);
  await signIn(p, size, 42);
  await shot(p, size, "11-ending");
  if (size.width === 390) await shot(p, size, "11-ending-full", true);
  await p.context().close();
}
await browser.close();

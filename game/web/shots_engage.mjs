// Screenshots of the engagement screens at 390x844 (iPhone 12-15), against one mock Pico.
//   game/web/shots_engage.sh OUTDIR     (starts the mock on 8048; needs PW and CHROME as in shots.mjs)
// The phone's clock is pinned (America/Chicago) so the timed job shows running or done.
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const PORT = process.env.PORT || 8048;
const size = { width: 390, height: 844, inset: "34px" };
const browser = await chromium.launch({ executablePath: process.env.CHROME });
let ua = 0;

async function page(day, when, crew = 0, colorScheme = "light") {
  const ctx = await browser.newContext({ userAgent: `Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 eng/${ua++}`,
    viewport: { width: size.width, height: size.height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme,
    timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); process.exitCode = 1; });
  await p.clock.setFixedTime(new Date(`2026-10-23T${when}:00-05:00`));
  await p.goto(`http://localhost:${PORT}/?day=${day}`);
  await p.addStyleTag({ content: `:root{--sb:${size.inset}}` });
  await p.click(`[data-who="${crew}"]`);
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector("#dock nav, .big");
  if (await p.$(".big")) { await p.click('[data-go="home"]'); await p.waitForSelector("#dock nav"); }
  return p;
}
async function shot(p, name, full = false) {
  if (full) await p.addStyleTag({ content: "#dock{position:static}main{padding-bottom:0!important}" });
  if (full) await p.evaluate(() => window.scrollTo(0, 0));
  await p.waitForTimeout(150);
  const f = `${out}/${name}-390x844.png`;
  await p.screenshot({ path: f, fullPage: full });
  console.log(f);
}
const goto = (p, r) => p.evaluate((r) => go(r), r);

let p = await page(22, "16:30");
await shot(p, "eng-01-home-last-night");
await shot(p, "eng-02-home-last-night-full", true);
await p.context().close();

p = await page(21, "09:10");
await shot(p, "eng-03-home-tonight");
await goto(p, "job/21");
await shot(p, "eng-06-job-running");
await p.context().close();

p = await page(22, "16:30");
await goto(p, "drop/22");
await shot(p, "eng-04-drop-sealed");
await p.click('[data-eng="open:22"]');
await p.waitForSelector(".card .lead");
await shot(p, "eng-05-drop-opened");
await goto(p, "job/22");
await shot(p, "eng-07-job-done");
await p.context().close();

p = await page(34, "12:05");
await goto(p, "gifts");
await shot(p, "eng-08-gifts-ask");
await p.click('[data-eng="to:3"]');
await p.click('[data-eng="item:2"]');
await shot(p, "eng-09-gifts-send-full", true);
await p.context().close();

p = await page(36, "18:40");
await goto(p, "streak");
await shot(p, "eng-10-streak-full", true);
await goto(p, "file");
await shot(p, "eng-12-file");
await shot(p, "eng-13-file-full", true);
await p.context().close();

p = await page(36, "18:40", 2);
await goto(p, "streak");
await shot(p, "eng-11-streak-sporadic-full", true);
await p.context().close();

p = await page(22, "16:30", 0, "dark");
await shot(p, "eng-14-home-dark");
await goto(p, "file");
await shot(p, "eng-15-file-dark");
await p.context().close();

p = await page(42, "20:00");
await p.waitForSelector(".epi");
await shot(p, "eng-16-ending-reread-full", true);
await p.context().close();
p = await page(42, "20:00");
await p.waitForSelector('[data-go^="log/"]');
await p.click('[data-go^="log/"]');
await shot(p, "eng-17-reread-log-day");
await p.context().close();

await browser.close();

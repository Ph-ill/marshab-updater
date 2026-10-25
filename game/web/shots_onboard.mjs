// Screenshots of the first run: names, crew code, meet, every intro and briefing card, and
// the Bluetooth contact marks (crew list, instruction gift picker, cargo picker), light and
// dark. Anything that would show story text gets placeholder text instead.
//   (shots_onboard.sh starts the mock Picos: 8052 light, 8053 dark, fresh, every code 1234)
//   PW=/path/to/node_modules/playwright-core CHROME=/usr/bin/google-chrome node web/shots_onboard.mjs OUTDIR
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const size = { width: 390, height: 844, inset: "34px" };
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
let ua = 0;
async function page(scheme) {
  const ctx = await browser.newContext({ userAgent: `Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 onb/${ua++}`,
    viewport: { width: size.width, height: size.height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: scheme });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); process.exitCode = 1; });
  return p;
}
async function shot(p, name, scheme) {
  // no story text in these: any log lines on screen become placeholders
  await p.evaluate((ph) => { for (const li of document.querySelectorAll("#v .log li")) li.textContent = ph; }, PH);
  await p.waitForTimeout(150);
  const f = `${out}/${name}-${scheme}.png`;
  await p.screenshot({ path: f });
  console.log(f);
}
for (const [i, scheme] of ["light", "dark"].entries()) {
  const p = await page(scheme);
  await p.goto(`http://localhost:${8052 + i}/?day=8`);
  await p.addStyleTag({ content: `:root{--sb:${size.inset}}` });
  await p.waitForSelector("[data-who]");
  await shot(p, "01-names", scheme);
  await p.click('[data-who="0"]');
  for (const k of "12") await p.click(`[data-key="${k}"]`);
  await shot(p, "02-crew-code", scheme);
  for (const k of "34") await p.click(`[data-key="${k}"]`);
  await p.waitForSelector(".big");
  await shot(p, "03-meet", scheme);
  await p.click("#dock .btn");
  await p.waitForSelector(".tut");
  const n = await p.evaluate(() => TUT().length);
  for (let c = 0; c < n; c++) {
    const k = await p.evaluate(() => TUT()[tutStep()][0].toLowerCase().replace(/[^a-z]+/g, "-"));
    await shot(p, `04-card-${String(c + 1).padStart(2, "0")}-${k}`, scheme);
    if (c < n - 1) { await p.click("[data-tut=next]"); await p.waitForFunction((c) => tutStep() === c, c + 1); }
  }
  await p.click("[data-tut=done]");
  await p.waitForSelector("#dock nav");
  await p.evaluate(() => go("crew"));
  await p.waitForSelector("[data-out]");
  await p.evaluate(() => { document.querySelector('[data-go^="crew/"]').closest("section").scrollIntoView(); scrollBy(0, -64); });
  await shot(p, "05-crew-nearby", scheme);
  await p.evaluate(() => go("act"));
  await p.click('[data-act="0"]');
  await shot(p, "06-instruction-gift-nearby", scheme);
  await p.evaluate(() => { draft = null; go("gifts"); });
  await p.waitForSelector('[data-eng^="to:"]');
  await p.click('[data-eng^="to:"]');
  await p.evaluate(() => document.querySelector('[data-eng^="to:"]').scrollIntoView({ block: "center" }));
  await shot(p, "07-cargo-gift-nearby", scheme);
  await p.context().close();
}
await browser.close();

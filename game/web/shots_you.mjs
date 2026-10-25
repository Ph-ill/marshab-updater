// Second-person UI screenshots (light, 390x844): home, who is aboard with your own row, your page,
// the plan sheet, gifts, watch duty, your crew file, meet and briefing cards.
// No story in these: the page gets text.json/engage.json with every card, epilogue,
// note, voice, habit, drop and job line swapped for placeholder text, and any log line
// on screen is replaced as well. Only the UI's own words are real.
//   game/web/shots_you.sh OUTDIR   (starts mocks on 8054 fresh and 8055; PW, CHROME as in shots.mjs)
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = process.argv[2] || "shots";
const size = { width: 390, height: 844, inset: "34px" };
const browser = await chromium.launch({ executablePath: process.env.CHROME });
const PH = "Placeholder text: story hidden from this screenshot.";
let ua = 0;

function blank(x, deep) {
  if (typeof x === "string") return deep && x.length > 18 && x.includes(" ") ? PH : x;
  if (Array.isArray(x)) return x.map((v) => blank(v, deep));
  if (x && typeof x === "object") return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, blank(v, deep)]));
  return x;
}
const STORY_T = ["cards", "epi", "reread", "notes", "reveal", "voice", "core"];
const STORY_E = ["drops", "jobs", "file"];
async function page(port, day, when, fresh = false) {
  const ctx = await browser.newContext({ userAgent: `Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 you/${ua++}`,
    viewport: { width: size.width, height: size.height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: "light",
    timezoneId: "America/Chicago" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => { console.error("pageerror", e.message); process.exitCode = 1; });
  for (const [path, keys] of [["/text.json", STORY_T], ["/engage.json", STORY_E]]) {
    await p.route(`**${path}*`, async (route) => {
      const j = await (await route.fetch()).json();
      for (const k of keys) if (k in j) j[k] = blank(j[k], true);
      if (j.cards) j.cards = j.cards.map((c) => ({ ...c, t: "Placeholder. " + PH, o: c.o.map((o) => ["Placeholder option", PH, ...o.slice(2)]) }));
      if (j.crew) j.habit = undefined;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(j) });
    });
  }
  await p.clock.setFixedTime(new Date(`2026-10-23T${when}:00-05:00`));
  await p.goto(`http://localhost:${port}/?day=${day}`);
  await p.addStyleTag({ content: `:root{--sb:${size.inset}}` });
  await p.waitForSelector("[data-who]");
  await p.click('[data-who="0"]');
  for (const k of "1234") await p.click(`[data-key="${k}"]`);
  if (fresh) return p;
  await p.waitForSelector("#dock nav, .kick.big");
  if (await p.$(".kick.big")) { await p.click("#dock .btn"); await p.waitForSelector(".kick.big", { state: "detached" }); }
  if (await p.$(".tut")) { await p.click("[data-tut=skip]"); await p.waitForSelector(".tut", { state: "detached" }); }
  await p.waitForSelector("#dock nav");
  return p;
}
async function shot(p, name, full = false) {
  await p.evaluate((ph) => {
    for (const li of document.querySelectorAll(".log li, .epi p")) li.textContent = ph;
  }, PH);
  if (full) await p.addStyleTag({ content: "#dock{position:static}main{padding-bottom:0!important}" });
  if (full) await p.evaluate(() => window.scrollTo(0, 0));
  await p.waitForTimeout(150);
  const f = `${out}/${name}-light-390x844.png`;
  await p.screenshot({ path: f, fullPage: full });
  console.log(f);
}
const goto = (p, r) => p.evaluate((r) => go(r), r);

let p = await page(8054, 8, "09:10", true);
await p.waitForSelector(".big");
await shot(p, "you-01-meet");
await p.click("#dock .btn");
await p.waitForSelector(".tut");
const n = await p.evaluate(() => TUT().length);
for (let c = 0; c < n; c++) {
  const k = await p.evaluate(() => TUT()[tutStep()][0].toLowerCase().replace(/[^a-z]+/g, "-"));
  await shot(p, `you-02-briefing-${String(c + 1).padStart(2, "0")}-${k}`);
  if (c < n - 1) { await p.click("[data-tut=next]"); await p.waitForFunction((c) => tutStep() === c, c + 1); }
}
await p.context().close();

p = await page(8055, 22, "16:30");
await shot(p, "you-03-home");
await p.evaluate(() => { document.querySelector('button.row[data-go="crew"]').closest("section").scrollIntoView(); scrollBy(0, -64); });
await shot(p, "you-04-crew-aboard-self");
await goto(p, "crew");
await p.waitForTimeout(200);
await shot(p, "you-05-your-crew-page");
await goto(p, "act");
await shot(p, "you-06-plan-sheet");
await p.click('[data-act="0"]');
await shot(p, "you-07-plan-gift");
await p.context().close();

p = await page(8055, 34, "12:05");
await goto(p, "gifts");
await shot(p, "you-08-gifts");
await p.context().close();

p = await page(8055, 36, "18:40");
await goto(p, "streak");
await shot(p, "you-09-watch-duty-full", true);
await p.context().close();
p = await page(8055, 36, "18:40");
await goto(p, "file");
await shot(p, "you-10-crew-file");
await p.context().close();
await browser.close();

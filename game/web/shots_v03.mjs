// 0.2.7 / 0.3.x screens against the board's own server code (tests/phone_serve.py), story
// text swapped for placeholders. One scenario per run:
//   node web/shots_v03.mjs safe PORT OUTDIR      safe mode (phone_serve.py --safe)
//   node web/shots_v03.mjs live PORT OUTDIR      Hail and the ship-to-ship switch (phone_serve.py --live)
//   node web/shots_v03.mjs duel PORT OUTDIR      Asteroid duel (phone_serve.py --live)
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
async function shot(p, name) { await p.waitForTimeout(250); await p.screenshot({ path: `${out}/${name}.png` }); console.log("shot " + name); }
const SCEN = {};
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
if (globalThis.EXTRA) Object.assign(SCEN, globalThis.EXTRA);
try { await SCEN[what](); } catch (e) { console.error(e); fails++; }
await browser.close();
console.log(fails ? `${fails} failed` : "all ok");
process.exit(fails ? 1 : 0);

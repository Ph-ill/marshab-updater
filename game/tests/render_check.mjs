// Renders build/season_story.bin with web/render.js and compares it with the Python
// renderer: the narrative (sim/out/narrative.txt, page headings included), the epilogue
// and coda (sim/out/epilogue.txt), and the epilogue fallback on three final states
// (build/season_end.json). Run after sim/season.py.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Renderer, pageHeading } from "../web/render.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const text = JSON.parse(readFileSync(join(root, "build/text.json"), "utf8"));
const story = readFileSync(join(root, "build/season_story.bin"));
let eng = null; // engagement words (tools/lve.py): gift lines need them
try { eng = JSON.parse(readFileSync(join(root, "build/engage.json"), "utf8")); } catch {}

function same(what, js, py) {
  if (js === py) return;
  const a = js.split("\n"), b = py.split("\n");
  const i = a.findIndex((l, k) => l !== b[k]);
  console.error(`render.js differs from sim/render.py in ${what} at line ${i + 1}:\n  js: ${a[i]}\n  py: ${b[i]}`);
  process.exit(1);
}

const lines = [];
let last = -1;
for (const [day, s] of new Renderer(text, eng).lines(story)) {
  if (day !== last) {
    lines.push("", pageHeading(day));
    last = day;
  }
  lines.push("  " + s);
}
const js = lines.join("\n").trim() + "\n";
same("narrative.txt", js, readFileSync(join(root, "sim/out/narrative.txt"), "utf8"));

// The reference season's epilogue: story lines only (Python passes the state too, but
// every astronaut has a story line there), then the coda.
const rd = new Renderer(text, eng);
const epi = rd.epilogue(story);
const coda = rd.coda(story);
const ejs = Object.keys(epi).sort((a, b) => a - b).map((c) => `${text.crew[c]}: ${epi[c]}\n`).join("")
  + (coda ? `${coda[0]}: ${coda[1]}\n` : "");
same("epilogue.txt", ejs, readFileSync(join(root, "sim/out/epilogue.txt"), "utf8"));

const cases = JSON.parse(readFileSync(join(root, "build/season_end.json"), "utf8"));
cases.forEach((k, i) => {
  const st = { trait: (c, a) => k.traits[c][a], bond: (c, j) => k.bonds[c][j] };
  const got = new Renderer(text).epilogue(new Uint8Array(0), st);
  same(`epilogue fallback case ${i + 1}`, JSON.stringify(got), JSON.stringify(k.lines));
});

// Second person (tests/test_you_voice.py writes build/season_you.json): the same season
// read from each of the eight ships, and every string filled with each role as the viewer.
const you = JSON.parse(readFileSync(join(root, "build/season_you.json"), "utf8"));
let nyou = 0;
for (let me = 0; me < text.crew.length; me++) {
  const k = you[me];
  const got = new Renderer(text, eng, me).lines(story).map(([d, s]) => `${d}\t${s}`);
  same(`ship ${me + 1}'s log`, got.join("\n"), k.lines.join("\n"));
  const e = new Renderer(text, eng, me).epilogue(story);
  same(`ship ${me + 1}'s epilogue`, JSON.stringify(Object.fromEntries(Object.entries(e).map(([c, s]) => [String(c), s]))), JSON.stringify(k.epilogue));
  nyou += got.length;
}
const dummy = { ...text, crew: ["Ann", "Bea", "Cy", ...text.crew.slice(3).map((_, i) => `X${i}`)] };
you.fills.forEach(([s, me, py], i) => {
  same(`string ${i + 1} with role ${me} as the viewer`, new Renderer(dummy, eng, me).fill(s, 0, 1, { T: 2 }), py);
});

for (const n of [1, 6, 7, 8, 42]) if (!/^LOG PAGE \d\d · DAYS? \d+(–\d+)?$/.test(pageHeading(n))) {
  console.error("bad page heading " + pageHeading(n));
  process.exit(1);
}
console.log(`render.js matches sim/render.py (${js.split("\n").length} lines, epilogue ${Object.keys(epi).length}+${coda ? 1 : 0}, fallback x${cases.length}; 8 viewers ${nyou} lines, ${you.fills.length} fills)`);

// Renders build/season_story.bin with web/render.js and compares it with the
// Python renderer's sim/out/narrative.txt. Run after sim/season.py.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Renderer } from "../web/render.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const text = JSON.parse(readFileSync(join(root, "build/text.json"), "utf8"));
const story = readFileSync(join(root, "build/season_story.bin"));
let eng = null; // engagement words (tools/lve.py): gift lines need them
try { eng = JSON.parse(readFileSync(join(root, "build/engage.json"), "utf8")); } catch {}
const lines = [];
let last = -1;
for (const [day, s] of new Renderer(text, eng).lines(story)) {
  if (day !== last) {
    lines.push("", `FLIGHT DAY ${String(day).padStart(2, "0")}`);
    last = day;
  }
  lines.push("  " + s);
}
const js = lines.join("\n").trim() + "\n";
const py = readFileSync(join(root, "sim/out/narrative.txt"), "utf8");
if (js !== py) {
  const a = js.split("\n"), b = py.split("\n");
  const i = a.findIndex((l, k) => l !== b[k]);
  console.error(`render.js differs from sim/render.py at line ${i + 1}:\n  js: ${a[i]}\n  py: ${b[i]}`);
  process.exit(1);
}
console.log(`render.js matches sim/render.py (${a_len(js)} lines)`);
function a_len(s) { return s.split("\n").length; }

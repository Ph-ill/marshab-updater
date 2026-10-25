// The Long Voyage: phone-side story renderer.
// The Pico sends 8-byte story entries; this turns them into sentences using text.json
// (served gzipped by the Pico). sim/render.py is the Python mirror, and
// tests/render_check.mjs checks both produce the same narrative.
//
// Entry: [day, code, card, a, b, c, d, e]   255 = none

export const O = {
  EVENT: 1, DEC_OPEN: 2, DEC_CLOSE: 3, DIL_OPEN: 4, DIL_CLOSE: 5, ACT: 6,
  MOVE: 7, NOTE: 8, END: 9, RES_OPEN: 10, RES_CLOSE: 11, SHORT: 12, GIFT: 13,
};
const NONE = 255;
const VOICE_CARDS = 2;

// Second person (sim/render.py has the same rules). Every ship reads the same story,
// so a line about the reader's own crew member is turned to "you" as it is drawn:
//   {A} {B} {T}       a name, or "you"/"You" for the reader (capital at a sentence start)
//   {A}'s             "your" for the reader
//   {A:checks}        a verb or pronoun that agrees with A: "check", "are" for "is",
//                     "your" for "their", "yourself" for "themselves"; {A:aches|ache}
//                     gives the reader's form outright
//   {A?mine|theirs}   whole wording: the first for the reader, the second otherwise
//   {AB:they}         the pair A and B: "you" when either is the reader ("yourselves")
// Inside double quotes nothing changes: a crewmate saying a name keeps the name.
// With no reader (me = 255, the simulator) every line reads exactly as written.
const YOU = {
  is: "are", was: "were", has: "have", does: "do", goes: "go", "isn't": "aren't", "wasn't": "weren't",
  "hasn't": "haven't", "doesn't": "don't", they: "you", them: "you", their: "your", theirs: "yours",
  themselves: "yourself", themself: "yourself", "they're": "you're", "they've": "you've",
  "they'd": "you'd", "they'll": "you'll",
};
// The pair A and B, when either reads: "you both" keeps it from sounding like you alone.
const PAIR = { they: "you both", themselves: "yourselves" };

export function second(w, pair = false) {
  const bar = w.indexOf("|");
  if (bar >= 0) return w.slice(bar + 1);
  const lo = w.toLowerCase();
  let r = pair ? PAIR[lo] || YOU[lo] : YOU[lo];
  if (r === undefined) {
    if (lo.length > 4 && /[^aeiou]ies$/.test(lo)) r = lo.slice(0, -3) + "y";
    else if (/(ss|sh|ch|x|zz|o)es$/.test(lo)) r = lo.slice(0, -2);
    else r = lo.endsWith("s") ? lo.slice(0, -1) : lo;
  }
  return w[0] !== lo[0] ? r[0].toUpperCase() + r.slice(1) : r;
}
const TOKEN = /\{(AB|[ABT])\?((?:[^{}|]|\{[^{}]*\})*)\|((?:[^{}]|\{[^{}]*\})*)\}|\{([ABT])\}'s\b|\{(\w+)(?::([^{}]+))?\}/g;
// Is the end of s inside double quotes, or at the start of a sentence?
const quoted = (s) => (s.split('"').length % 2 === 0) || s.lastIndexOf("\u201c") > s.lastIndexOf("\u201d");
// A quoted question or exclamation followed by its speech verb is one sentence:
// "Ready?" you ask. Anything else after it starts a new one.
const TAG = /^\s*\{[ABT]:(asks|says|answers|tells|calls|adds|replies|whispers|shouts)\}/;
const opening = (s, rest = "") => {
  const p = s.replace(/\s+$/, "");
  if (/[?!]["\u201d]$/.test(p) && TAG.test(rest)) return false;
  return p === "" || /[.!?]["\u201d)]*$/.test(p);
};
const STORY = [O.EVENT, O.DEC_OPEN, O.DIL_OPEN, O.RES_OPEN]; // codes that cast a card

// Log page n covers flight days [a, b]: pages 1-6 are one day each (Earth orbit and
// the departure burn), then five days a page from page 7. sim/render.py page_heading.
export function pageDays(n) {
  const a = n <= 6 ? n : 7 + 5 * (n - 7);
  return [a, n <= 6 ? a : a + 4];
}
export function pageHeading(n) {
  const [a, b] = pageDays(n);
  return `LOG PAGE ${String(n).padStart(2, "0")} \u00b7 ${a === b ? "DAY " + a : `DAYS ${a}\u2013${b}`}`;
}

export class Renderer {
  constructor(text, eng = null, me = NONE) {
    this.t = text;
    this.e = eng; // engage.json, optional: without it gift lines are skipped
    this.me = me; // the reader's own crew member (ship - 1): their lines read "you"
    this.roles = new Map(); // card -> [A, B] from the entry that opened it
    this.ties = 0; // tie closes seen so far: steps through sys.dec_tie
    this.vcards = {}; // crew -> cards that printed their voice this season
    this.card = NONE;
  }

  name(c) {
    return c !== NONE && c < this.t.crew.length ? this.t.crew[c] : "someone";
  }

  // A crewmate's own sign-off (roster.lv `voice`), for {Av}/{Bv}.
  // Each crewmate's voice prints on at most VOICE_CARDS cards a season (render.py too).
  voice(c) {
    const v = this.t.voice;
    if (!v || c === NONE || c >= v.length) return "Out.";
    const seen = this.vcards[c] || (this.vcards[c] = []);
    if (!seen.includes(this.card)) {
      if (seen.length >= VOICE_CARDS) return "Noted.";
      seen.push(this.card);
    }
    return v[c];
  }

  // kw.T may be a crew index (a role like A and B) or ready-made text.
  fill(tpl, A = NONE, B = NONE, kw = {}) {
    const me = this.me;
    if (me !== NONE) {
      // "Kim and you" reads better as "you and Kim".
      if (B === me) tpl = tpl.split("{A} and {B}").join("{B} and {A}");
      else if (A === me) tpl = tpl.split("{B} and {A}").join("{A} and {B}");
    }
    return this.fillAt(tpl, { A, B, T: typeof kw.T === "number" ? kw.T : undefined }, kw, "");
  }

  fillAt(tpl, R, kw, pre) {
    let out = "", at = 0;
    const me = this.me;
    for (const m of tpl.matchAll(TOKEN)) {
      out += tpl.slice(at, m.index);
      at = m.index + m[0].length;
      const so = pre + out;
      // hit: this line spoke to the reader (their own crew page lists these as "Lately").
      const mine = (r) => me !== NONE && (r === "AB" ? R.A === me || R.B === me : R[r] === me) && !quoted(so) && (this.hit = true);
      const role = (k) => k === "A" || k === "B" || k === "AB" || (k === "T" && R.T !== undefined);
      if (m[1]) out += this.fillAt(mine(m[1]) ? m[2] : m[3], R, kw, so);
      else if (m[4]) out += mine(m[4]) ? (opening(so, tpl.slice(at)) ? "Your" : "your") : this.name(R[m[4]]) + "'s";
      else {
        const k = m[5];
        if (m[6] !== undefined) {
          const w = m[6].split("|")[0];
          out += role(k) && mine(k) ? second(m[6], k === "AB") : w;
        } else if (k === "Av" || k === "Bv") out += this.voice(k === "Av" ? R.A : R.B);
        else if (role(k) && k !== "AB") out += mine(k) ? (opening(so, tpl.slice(at)) ? "You" : "you") : this.name(R[k]);
        else out += k in kw ? String(kw[k]) : m[0];
      }
    }
    return out + tpl.slice(at);
  }

  entry(e) {
    const [, code, card, a, b, c, d] = e;
    const t = this.t, sy = t.sys;
    const cd = card !== NONE ? t.cards[card] : null;
    this.card = card;
    switch (code) {
      case O.EVENT: {
        let s = this.fill(cd.t, a, b);
        if (c !== NONE) s += " " + this.fill(cd.o[c][1], a, b);
        return s;
      }
      case O.DEC_OPEN:
      case O.RES_OPEN: {
        this.roles.set(card, [a, b]);
        const opts = cd.o.map((o) => this.fill(o[0], a, b)).join(" / ");
        const lead = code === O.DEC_OPEN ? sy.dec_open : sy.res_open;
        return `${lead} ${this.fill(cd.t, a, b)} [${opts}]`;
      }
      case O.DIL_OPEN:
        this.roles.set(card, [a, NONE]);
        return this.fill(sy.dil_open, a) + " " + this.fill(cd.t, a);
      case O.DEC_CLOSE:
      case O.RES_CLOSE: {
        const [A, B] = this.roles.get(card) || [NONE, NONE];
        const opt = this.fill(cd.o[a][0], A, B);
        let lead;
        if (code === O.RES_CLOSE) lead = this.fill(sy[c ? "res_default" : "res_close"], NONE, NONE, { opt });
        else if (c === 1) lead = this.fill(sy.dec_lean, NONE, NONE, { opt });
        else if (c === 2) {
          // dec_tie may be a list: each tie close in the log takes the next wording,
          // so a season's ties never repeat (render.py does the same).
          const tie = Array.isArray(sy.dec_tie) ? sy.dec_tie[this.ties++ % sy.dec_tie.length] : sy.dec_tie;
          lead = this.fill(tie, NONE, NONE, { opt, n: b });
        }
        else lead = this.fill(sy.dec_close, NONE, NONE, { opt, n: b });
        return lead + " " + this.fill(cd.o[a][1], A, B);
      }
      case O.DIL_CLOSE: {
        const opt = cd.o[b][0];
        return this.fill(sy[c ? "dil_self" : "dil_you"], a, NONE, { opt }) + " " + this.fill(cd.o[b][1], a);
      }
      case O.ACT: {
        const act = t.actions[b];
        const p = e[7];
        const axis = b === 1 && p < 3 ? t.axis_words[p][c === 0 ? 1 : 0] : "";
        const res = b === 2 && p < 3 ? t.res_words[p] : "";
        return this.fill(act[d ? "self" : "you"], a, NONE, { axis, res, T: c });
      }
      case O.MOVE:
        return this.fill(c === a ? sy.home : sy.move, a, NONE, { S: t.ships[c] });
      case O.NOTE:
        return this.fill(sy.note, a, NONE, { T: c, line: t.notes[b] });
      case O.GIFT: {
        const g = this.e && this.e.gifts;
        if (!g || b >= g.items.length || d > 2) return null;
        return this.fill(g.sys[["give", "ask", "answer"][d]], a, NONE, { T: c, item: g.items[b][0] });
      }
      case O.SHORT:
        return sy.short;
      case O.END:
        return sy.end + " " + this.fill(cd.t, a, b);
      default:
        return null; // unknown code from a newer pack: skip, don't break the page
    }
  }

  // Returns [[day, text], ...]. routine=false hides chores the astronauts chose
  // themselves (the page folds them into one "kept the ship running" line).
  lines(out, routine = false) {
    const res = [];
    this.ties = 0;
    this.vcards = {};
    for (let i = 0; i + 8 <= out.length; i += 8) {
      const e = Array.from(out.slice(i, i + 8));
      if (!routine && e[1] === O.ACT && e[6] === 1 && e[4] !== 0) continue;
      const s = this.entry(e);
      if (s) res.push([e[0], s.trim()]);
    }
    return res;
  }

  // End screen, one line per astronaut: text.json epi.story is a priority list of
  // [card, line], and each astronaut gets the first line whose card cast them as role A.
  // With st ({trait(c, a), bond(c, j)}) any gap is filled from the final state, so
  // everyone has a line. Returns {crew: line}. Same rules as render.py epilogue().
  epilogue(out, st = null) {
    const first = new Set();
    for (let i = 0; i + 8 <= out.length; i += 8) {
      if (STORY.includes(out[i + 1]) && out[i + 3] !== NONE) first.add(out[i + 2] * 256 + out[i + 3]);
    }
    const lines = {}, epi = this.t.epi || {}, n = this.t.crew.length;
    for (const [card, line] of epi.story || []) {
      for (let c = 0; c < n; c++) if (!(c in lines) && first.has(card * 256 + c)) lines[c] = line;
    }
    if (st) this.epilogueFallback(lines, epi, st);
    for (const c in lines) lines[c] = this.fill(lines[c], +c); // "their" is "your" on your own line
    return lines;
  }

  // Strongest trait past `cut` (epi.axis [positive, negative] per axis), else the
  // closest bond past `cut` (epi.bond), else epi.plain; a line already shown is skipped.
  epilogueFallback(lines, epi, st, cut = 20) {
    const n = this.t.crew.length, ax = epi.axis || [];
    const used = new Set(Object.values(lines));
    const by = (f) => (x, y) => f(y) - f(x); // descending; sort is stable, like sorted()
    for (let c = 0; c < n; c++) {
      if (c in lines) continue;
      const picks = [];
      for (const a of [...ax.keys()].sort(by((a) => Math.abs(st.trait(c, a))))) {
        const v = st.trait(c, a);
        if (Math.abs(v) >= cut) picks.push(ax[a][v >= 0 ? 0 : 1]);
      }
      if (epi.bond) {
        const j = [...Array(n).keys()].filter((j) => j !== c).sort(by((j) => st.bond(c, j)))[0];
        if (j !== undefined && st.bond(c, j) >= cut) picks.push(this.fill(epi.bond, NONE, NONE, { T: j }));
      }
      picks.push(epi.plain || "");
      const line = picks.find((p) => p && !used.has(p)) ?? picks[picks.length - 1];
      if (line) {
        lines[c] = line;
        used.add(line);
      }
    }
  }

  // The line for someone who isn't crew (epi.coda {name, lines}): the first card in
  // its list that fired, in any role. Returns [name, line] or null.
  coda(out) {
    const cd = (this.t.epi || {}).coda;
    if (!cd) return null;
    const fired = new Set();
    for (let i = 0; i + 8 <= out.length; i += 8) {
      if (STORY.includes(out[i + 1]) || out[i + 1] === O.END) fired.add(out[i + 2]);
    }
    const hit = cd.lines.find(([card]) => fired.has(card));
    return hit ? [cd.name, hit[1]] : null;
  }
}

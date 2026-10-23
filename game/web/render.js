// The Long Voyage: phone-side story renderer.
// The Pico sends 8-byte story entries; this turns them into sentences using text.json
// (served gzipped by the Pico). sim/render.py is the Python mirror, and
// tests/render_check.mjs checks both produce the same narrative.
//
// Entry: [day, code, card, a, b, c, d, e]   255 = none

export const O = {
  EVENT: 1, DEC_OPEN: 2, DEC_CLOSE: 3, DIL_OPEN: 4, DIL_CLOSE: 5, ACT: 6,
  MOVE: 7, NOTE: 8, END: 9, RES_OPEN: 10, RES_CLOSE: 11, SHORT: 12,
};
const NONE = 255;

export class Renderer {
  constructor(text) {
    this.t = text;
    this.roles = new Map(); // card -> [A, B] from the entry that opened it
    this.ties = 0; // tie closes seen so far: steps through sys.dec_tie
  }

  name(c) {
    return c !== NONE && c < this.t.crew.length ? this.t.crew[c] : "someone";
  }

  fill(tpl, A = NONE, B = NONE, kw = {}) {
    return tpl.replace(/\{(\w+)\}/g, (m, k) => {
      if (k === "A") return this.name(A);
      if (k === "B") return this.name(B);
      return k in kw ? String(kw[k]) : m;
    });
  }

  entry(e) {
    const [, code, card, a, b, c, d] = e;
    const t = this.t, sy = t.sys;
    const cd = card !== NONE ? t.cards[card] : null;
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
        return this.fill(act[d ? "self" : "you"], a, NONE, { axis, res, T: this.name(c) });
      }
      case O.MOVE:
        return this.fill(c === a ? sy.home : sy.move, a, NONE, { S: t.ships[c] });
      case O.NOTE:
        return this.fill(sy.note, a, NONE, { T: this.name(c), line: t.notes[b] });
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
    for (let i = 0; i + 8 <= out.length; i += 8) {
      const e = Array.from(out.slice(i, i + 8));
      if (!routine && e[1] === O.ACT && e[6] === 1 && e[4] !== 0) continue;
      const s = this.entry(e);
      if (s) res.push([e[0], s.trim()]);
    }
    return res;
  }
}

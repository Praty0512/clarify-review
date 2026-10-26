/**
 * Prose placeholders for the paper: text lives in docs/prose_v3.json.
 *
 * PROSE("paper.results.v3_effect") returns the text for that id with every
 * {key.path:fmt} token replaced from numbers.json. Same tokens, same formats
 * as docs/prose.py. An empty or missing placeholder THROWS, unless
 * ALLOW_EMPTY_PROSE=1, which renders the visible marker "[[PROSE:<id>]]"
 * (scaffold builds into a scratch folder only).
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const NUMBERS = JSON.parse(fs.readFileSync(path.join(__dirname, "numbers.json"), "utf8"));
let DATA = null;
const USED = new Set();
const TOKEN = /\{([A-Za-z0-9_.]+)(?::([a-z0-9]+))?\}/g;
const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
  "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
  "nineteen", "twenty"];

class PlaceholderError extends Error {}

const allowEmpty = () => !["", "0", undefined].includes(process.env.ALLOW_EMPTY_PROSE);
const halfUp = x => Math.floor(x + 0.5);
const fixed = (x, d) => { const k = 10 ** d, a = Math.abs(x); return ((x < 0 ? -1 : 1) * Math.round((a + Number.EPSILON) * k) / k).toFixed(d); };
const isNum = v => typeof v === "number" && Number.isFinite(v);

function fmt(value, spec, tok) {
  if (value === null || value === undefined) return "n/a";
  const num = () => {
    if (!isNum(value)) throw new PlaceholderError(`token {${tok}}: not a number (${JSON.stringify(value)})`);
    return value;
  };
  if (spec === undefined || spec === "str") {
    if (typeof value === "object" || typeof value === "boolean")
      throw new PlaceholderError(`token {${tok}}: needs a format`);
    if (typeof value === "number" && !Number.isInteger(value))
      throw new PlaceholderError(`token {${tok}}: a float needs a format (pct, f2, ...)`);
    return String(value);
  }
  switch (spec) {
    case "pct": return `${halfUp(num() * 100)}%`;
    case "f1": return fixed(num(), 1);
    case "f2": return fixed(num(), 2);
    case "f3": return fixed(num(), 3);
    case "p2": return num() < 0.005 ? "<0.01" : fixed(num(), 2);
    case "int": return String(halfUp(num()));
    case "k": return halfUp(num()).toLocaleString("en-US");
    case "word": { const n = halfUp(num()); return n >= 0 && n < WORDS.length ? WORDS[n] : String(n); }
    case "ci":
      if (!Array.isArray(value) || value.length !== 2) throw new PlaceholderError(`token {${tok}}: ci needs a two-element list`);
      return `${fixed(Number(value[0]), 2)} to ${fixed(Number(value[1]), 2)}`;
    default: throw new PlaceholderError(`token {${tok}}: unknown format '${spec}'`);
  }
}

function lookup(p) {
  let cur = NUMBERS;
  for (const seg of p.split(".")) {
    if (Array.isArray(cur) && /^\d+$/.test(seg) && Number(seg) < cur.length) cur = cur[Number(seg)];
    else if (cur !== null && typeof cur === "object" && !Array.isArray(cur) && seg in cur) cur = cur[seg];
    else throw new PlaceholderError(`unknown key path '${p}' (stopped at '${seg}')`);
  }
  return cur;
}

const render = text => text.replace(TOKEN, (_, p, spec) => fmt(lookup(p), spec, p + (spec ? ":" + spec : "")));

function PROSE(id) {
  USED.add(id);
  if (DATA === null) {
    try { DATA = JSON.parse(fs.readFileSync(path.join(ROOT, "docs", "prose_v3.json"), "utf8")); }
    catch (e) { throw new PlaceholderError(`cannot read docs/prose_v3.json: ${e.message}`); }
  }
  if (!(id in DATA)) throw new PlaceholderError(`placeholder '${id}' is not in prose_v3.json`);
  const t = DATA[id];
  if (typeof t !== "string" || !t.trim()) {
    if (allowEmpty()) return `[[PROSE:${id}]]`;
    throw new PlaceholderError(`placeholder '${id}' is empty in prose_v3.json (set ALLOW_EMPTY_PROSE=1 for a scaffold build)`);
  }
  return render(t.trim());
}

module.exports = { PROSE, render, fmt, lookup, PlaceholderError, USED };

// Crew codes for The Long Voyage. Phill sets each person's 4-digit code here, once, and the same
// codes go onto every ship, because people sign in on whichever ship's hotspot they're near.
//
// The board gets data/crew.json: a fleet salt and sha256(salt || crew byte || digits) per person
// (game/lv/codes.py checks it). That keeps the digits out of a file listing, nothing more: with
// 10,000 possible codes the file gives them up in a moment. The board's 5-try lockout is what
// slows down guessing at the page.
//
// This browser keeps the plain codes and the salt in localStorage, so the next board gets the
// same ones and the list can be copied out to hand round. Clear it with "Forget codes".
export const CREW = ['Phill', 'Jacques', 'Kim', 'Jai', 'Michelle', 'Diego', 'Dorian', 'Marco'];  // = game/content/roster.lv
export const CREW_CONFIG_PATH = 'data/crew.json';
export const CODES_MEMORY_KEY = 'lv.crewCodes.v1';

const hex = bytes => [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
const unhex = s => Uint8Array.from(s.match(/../g) || [], h => Number.parseInt(h, 16));

export function newSalt(){ return hex(crypto.getRandomValues(new Uint8Array(16))); }

export function randomCode(){
  // rejection sampling so every code from 0000 to 9999 is equally likely
  const b = new Uint16Array(1);
  do{ crypto.getRandomValues(b); }while(b[0] >= 60000);
  return String(b[0] % 10000).padStart(4, '0');
}

// codes: 8 strings, each '' (not set up) or exactly 4 digits. At least one has to be set.
export function validateCodes(codes){
  if(!Array.isArray(codes) || codes.length !== CREW.length) throw new Error(`need ${CREW.length} codes`);
  const out = codes.map((c, i) => {
    const s = String(c ?? '').trim();
    if(s && !/^\d{4}$/.test(s)) throw new Error(`${CREW[i]}'s code must be 4 digits (or blank for not set up)`);
    return s;
  });
  if(!out.some(Boolean)) throw new Error('set at least one code');
  return out;
}

// Names that share a code: allowed, since each name checks its own, but worth a warning.
export function sharedCodes(codes){
  const seen = new Map();
  codes.forEach((c, i) => { if(c) seen.set(c, [...(seen.get(c) || []), CREW[i]]); });
  return [...seen.values()].filter(names => names.length > 1);
}

export async function digest(saltHex, crew, code){
  const salt = unhex(saltHex);
  const data = new Uint8Array(salt.length + 1 + 4);
  data.set(salt, 0);
  data[salt.length] = crew;
  data.set(new TextEncoder().encode(code), salt.length + 1);
  return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', data)));
}

export async function crewConfig(codes, saltHex){
  if(!/^[0-9a-f]{32}$/.test(saltHex)) throw new Error('salt must be 32 hex characters');
  const ok = validateCodes(codes);
  return { schema: 1, salt: saltHex, codes: await Promise.all(ok.map((c, i) => c ? digest(saltHex, i, c) : null)) };
}

// "Phill 1234" lines, for handing the codes out.
export function codeList(codes){
  return CREW.map((n, i) => `${n.padEnd(9)} ${codes[i] || '(not set up)'}`).join('\n');
}

function store(storage){
  if(storage !== undefined) return storage;
  try{ return globalThis.localStorage || null; }catch(_err){ return null; }
}

export function loadCodes(storage){
  const s = store(storage);
  try{
    const v = JSON.parse(s?.getItem(CODES_MEMORY_KEY) || 'null');
    if(v && /^[0-9a-f]{32}$/.test(v.salt) && Array.isArray(v.codes) && v.codes.length === CREW.length) return v;
  }catch(_err){}
  return null;
}

export function saveCodes({ salt, codes }, storage){
  const s = store(storage);
  if(s){ try{ s.setItem(CODES_MEMORY_KEY, JSON.stringify({ salt, codes })); }catch(_err){} }
}

export function forgetCodes(storage){
  const s = store(storage);
  if(s){ try{ s.removeItem(CODES_MEMORY_KEY); }catch(_err){} }
}

export async function writeCrewConfig(device, cfg){
  const payload = JSON.stringify({ ...cfg, updated_at: new Date().toISOString() });
  const code = `
try:
    import uos as os
except ImportError:
    import os
import json
payload = ${JSON.stringify(payload)}
d = json.loads(payload)
assert len(d['codes']) == 8
try:
    os.mkdir('data')
except OSError:
    pass
with open('data/crew.tmp', 'w') as f:
    f.write(payload)
with open('data/crew.tmp') as f:
    json.loads(f.read())
try:
    os.remove('data/crew.json')
except OSError:
    pass
os.rename('data/crew.tmp', 'data/crew.json')
print('crew-ok')
`;
  const { stdout } = await device.exec(code, { timeoutMs: 12000 });
  if(!stdout.includes('crew-ok')) throw new Error('device did not confirm the crew codes write');
  return JSON.parse(payload);
}

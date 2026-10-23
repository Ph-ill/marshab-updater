// Remembers, in this browser's localStorage, which bench role was last saved to which board, so the
// ship config panel can suggest the other role for the next board and warn before two boards end up
// with the same role (the same hotspot, and BLE peers that ignore each other).
// Boards are told apart by machine.unique_id(); without it every save counts as "another board".
import { hotspotForRole } from './ship-config.js';

export const ROLE_MEMORY_KEY = 'lv.benchRoles.v1';
const KEEP = 12;

function store(storage){
  if(storage !== undefined) return storage;
  try{ return globalThis.localStorage || null; }catch(_err){ return null; } // blocked storage throws
}

export function loadRoleHistory(storage){
  const s = store(storage);
  if(!s) return [];
  try{
    const list = JSON.parse(s.getItem(ROLE_MEMORY_KEY) || '[]');
    return Array.isArray(list) ? list.filter(e => e && typeof e === 'object') : [];
  }catch(_err){
    return [];
  }
}

// Newest first; one entry per board id (entries without an id are kept as they come).
export function recordRole({ uid = null, role = null, ship_id = null, ship_name = null, at = new Date().toISOString() }, storage){
  const s = store(storage);
  const entry = { uid, role: role || null, ship_id, ship_name, at };
  const list = [entry, ...loadRoleHistory(s).filter(e => !uid || e.uid !== uid)].slice(0, KEEP);
  if(s){ try{ s.setItem(ROLE_MEMORY_KEY, JSON.stringify(list)); }catch(_err){} }
  return list;
}

// The most recent save that was for a different board than `uid`.
export function lastOtherBoard(history, uid){
  return history.find(e => !uid || !e.uid || e.uid !== uid) || null;
}

// Role to preselect for this board: one that the last other board does not use (same hotspot counts
// as the same role, so "none" and A clash). null when there is nothing to go on.
export function suggestRole(history, uid, roles){
  const last = lastOtherBoard(history, uid);
  if(!last || !roles?.length) return null;
  const taken = hotspotForRole(last.role, roles);
  return roles.find(r => hotspotForRole(r, roles) !== taken) || null;
}

// The last other board if saving `role` here would give it the same hotspot, else null.
export function roleClash(history, uid, role, roles){
  const last = lastOtherBoard(history, uid);
  if(!last || !roles?.length) return null;
  return hotspotForRole(last.role, roles) === hotspotForRole(role, roles) ? last : null;
}

export function describeBoard(entry){
  const who = entry.ship_name || (entry.ship_id ? `ship #${entry.ship_id}` : 'a board');
  const bits = [];
  if(entry.uid) bits.push(`id ${entry.uid}`);
  if(entry.at) bits.push(`saved ${new Date(entry.at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}`);
  return bits.length ? `${who} (${bits.join(', ')})` : who;
}

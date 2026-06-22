// src/gift.mjs
// Pure, hardware-free reducers for the MarsHab gift + passport lifecycle.
// See docs/GIFT_PROTOCOL.md. No DOM, no network, no side effects: every function
// takes plain state and returns plain state, so tests/ can drive them directly.
// The build step inlines this into the single-file index.html for the Pico.

let _seq = 0;
export function makeNonce(prefix = 'gn', rng = Math.random) {
  return `${prefix}_${Math.floor(rng() * 1e9).toString(36)}_${(_seq++).toString(36)}`;
}

// --- Buy (home hab, owner) -------------------------------------------------
// Verifies the item is gift-only, you aren't already carrying, and you can afford it.
// On success: deduct credits, set carriedGift on the save, and emit a passport patch.
export function buyGift(homeSave, catalog, itemId, opts = {}) {
  const item = catalog.items[itemId];
  if (!item) return { error: 'unknown_item' };
  if (!item.giftOnly) return { error: 'not_gift_only' };          // I-spec: gift-only enforced
  if (homeSave.carriedGift) return { error: 'already_carrying' }; // I2 single slot
  if ((homeSave.credits || 0) < item.price) return { error: 'insufficient_credits' };

  const giftNonce = opts.nonce || makeNonce('gn', opts.rng);
  const carried = { itemId, forName: opts.forName || '', giftNonce };
  const homeSaveNext = { ...homeSave, credits: homeSave.credits - item.price, carriedGift: carried }; // I5
  return { homeSave: homeSaveNext, passportPatch: { carriedGift: { ...carried } } };
}

// --- Deliver (host hab) ----------------------------------------------------
// Idempotent on (passportId, itemId, giftNonce). deliveryLedger maps that key -> receipt.
// Retries return the same receipt and place nothing new (I3). Placement is tagged with
// the giver's name (I6).
export function deliverGift(hostSave, deliveryLedger, passport, cell, now = Date.now(), opts = {}) {
  const cg = passport.carriedGift;
  if (!cg) return { error: 'no_carried_gift' };

  const key = `${passport.passportId}|${cg.itemId}|${cg.giftNonce}`;
  const ledger = { ...deliveryLedger };
  if (ledger[key]) {
    return { hostSave, deliveryLedger: ledger, receipt: ledger[key], duplicate: true }; // I3
  }

  const uid = opts.uid || makeNonce('g', opts.rng);
  const placed = { uid, itemId: cg.itemId, cell, rot: 0 };
  const received = { uid, itemId: cg.itemId, cell, fromName: passport.name || 'someone', ts: now }; // I6
  const hostSaveNext = {
    ...hostSave,
    room: { ...hostSave.room, placed: [...hostSave.room.placed, placed] },
    giftsReceived: [...(hostSave.giftsReceived || []), received ],
  };
  const receipt = {
    giftNonce: cg.giftNonce,
    itemId: cg.itemId,
    hostHabId: opts.hostHabId || hostSave.habId || '',
    fromName: passport.name || '',
    ts: now,
  };
  ledger[key] = receipt;
  return { hostSave: hostSaveNext, deliveryLedger: ledger, receipt };
}

// --- Client: stamp the passport after a successful delivery ----------------
export function applyDeliveryToPassport(passport, receipt) {
  return {
    ...passport,
    carriedGift: null,
    pendingReceipts: [...(passport.pendingReceipts || []), receipt ],
  };
}

// --- Reconcile (home login) ------------------------------------------------
// Retire any carried gift whose nonce matches a receipt the courier brought home.
// Closes conservation (I1). Unmatched receipts (already reconciled / foreign) are dropped.
export function reconcile(homeSave, passport) {
  const receipts = passport.pendingReceipts || [];
  let save = homeSave;
  for (const r of receipts) {
    if (save.carriedGift && save.carriedGift.giftNonce === r.giftNonce) {
      save = {
        ...save,
        carriedGift: null,
        deliveredReceipts: [...(save.deliveredReceipts || []), r ],
      };
    }
  }
  return { homeSave: save, passport: { ...passport, pendingReceipts: [] } };
}

// --- Mint passport from home save ------------------------------------------
// Includes carriedGift if one is in transit, so a wiped courier can be regenerated
// from the durable home save and STILL deliver with the same nonce (I4).
export function mintPassport(homeSave, habId, now = Date.now(), opts = {}) {
  return {
    v: 1,
    passportId: homeSave.passportId || opts.passportId || makeNonce('ppt', opts.rng),
    name: (homeSave.owner && homeSave.owner.name) || 'crew',
    look: (homeSave.owner && homeSave.owner.look) || {},
    carriedGift: homeSave.carriedGift ? { ...homeSave.carriedGift } : null, // I4
    issuedBy: habId,
    issuedTs: now,
    pendingReceipts: [],
  };
}

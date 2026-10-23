# The shared choice log: a set of records keyed by (day, ship, kind, sub).
# Merging is a set union, so the result doesn't depend on the order or timing
# in which records arrive. Records index by effective day so the engine can ask
# "what takes effect today?" without scanning the whole log.
import sys

from lv import record as R

# A long sync merges hundreds of records back to back. On the Pico's heap that makes many
# small dict/list resizes, and without a collection in between the heap fragments until a
# resize fails with MemoryError although most of the heap is free (seen on MicroPython's
# 32-bit port at ~220 records with 172 KB free). So the log collects every GC_EVERY new
# records. CPython doesn't need it (and the sims would slow down), so there it is off.
GC_EVERY = 32
if sys.implementation.name == "micropython":
    import gc
    _collect = gc.collect
else:  # pragma: no cover - CPython
    _collect = None

NEW = 1
DUP = 0
REPLACED = 2
STALE = -1
BAD = -2


class ChoiceLog:
    def __init__(self, fleet_key, max_schema=R.SCHEMA):
        self.fk = bytes(fleet_key)
        self.max_schema = max_schema
        self.recs = {}      # int key -> 13-byte record
        self.by_eff = {}    # effective day -> list of keys (unsorted)
        self.unknown = []   # newer-schema records: kept and relayed, never interpreted
        self.collect = _collect   # called every GC_EVERY new records (None: never)
        self._since = 0
        self.gcs = 0

    def __len__(self):
        return len(self.recs)

    def merge(self, rec, check=True):
        # Returns NEW / DUP / REPLACED / STALE / BAD.
        rec = bytes(rec)
        if check and not R.valid(self.fk, rec):
            return BAD
        if R.schema(rec) > self.max_schema:
            if rec not in self.unknown:
                self.unknown.append(rec)
                return NEW
            return DUP
        k = R.key(rec)
        old = self.recs.get(k)
        if old is None:
            self._since += 1
            if self._since >= GC_EVERY and self.collect:
                self._since = 0
                self.gcs += 1
                self.collect()
            self.recs[k] = rec
            e = R.eff_day(rec)
            lst = self.by_eff.get(e)
            if lst is None:
                self.by_eff[e] = [k]
            else:
                lst.append(k)
            return NEW
        if old == rec:
            return DUP
        so, sn = R.seq(old), R.seq(rec)
        if sn > so or (sn == so and rec > old):
            # Same key means same authored day and delay class is the author's;
            # if the delay changed, move the index entry.
            eo, en = R.eff_day(old), R.eff_day(rec)
            if eo != en:
                self.by_eff[eo].remove(k)
                lst = self.by_eff.get(en)
                if lst is None:
                    self.by_eff[en] = [k]
                else:
                    lst.append(k)
            self.recs[k] = rec
            return REPLACED
        return STALE

    def effective(self, day):
        # Records taking effect on this day, in key order.
        ks = self.by_eff.get(day)
        if not ks:
            return []
        ks = sorted(ks)
        return [self.recs[k] for k in ks]

    def answers(self, kind, card, first_day, close_day):
        # Votes or dilemma answers for one card, authored on or after first_day and
        # in effect by close_day. One per ship: the latest authored day wins
        # (merge already chose the highest seq inside one day). Returns a list of
        # (ship, option) sorted by ship.
        best = {}
        for e in range(first_day + 1, close_day + 1):
            ks = self.by_eff.get(e)
            if not ks:
                continue
            for k in ks:
                r = self.recs[k]
                if R.kind(r) != kind or r[5] != card or R.day(r) < first_day:
                    continue
                s = R.ship(r)
                if s == R.ADMIN_SHIP:
                    continue
                cur = best.get(s)
                if cur is None or R.key(r) > R.key(cur):
                    best[s] = r
        out = []
        for s in sorted(best):
            out.append((s, best[s][6]))
        return out

    def all_records(self):
        return [self.recs[k] for k in sorted(self.recs)] + list(self.unknown)

    def digest(self):
        # Order-independent digest for adverts: sha256 over the sorted records.
        try:
            from hashlib import sha256
        except ImportError:  # pragma: no cover
            from uhashlib import sha256
        h = sha256()
        for k in sorted(self.recs):
            h.update(self.recs[k])
        return h.digest()[:4]

    def seq_vector(self, ships=7):
        # Highest sequence number seen per author ship: what status adverts carry.
        v = [0] * ships
        for r in self.recs.values():
            s = R.ship(r)
            if s < ships:
                q = R.seq(r)
                if q > v[s]:
                    v[s] = q
        return v

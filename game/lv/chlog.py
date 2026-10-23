# The shared choice log: a set of records keyed by (day, ship, kind, sub).
# Merging is a set union, so the result doesn't depend on the order or timing
# in which records arrive. Records index by effective day so the engine can ask
# "what takes effect today?" without scanning the whole log.
from lv import record as R

NEW = 1
DUP = 0
REPLACED = 2
STALE = -1
BAD = -2
SHARD = 19   # key bits below the shard: day << 16, so 8 authored days per shard


class ChoiceLog:
    def __init__(self, fleet_key, max_schema=R.SCHEMA):
        self.fk = bytes(fleet_key)
        self.max_schema = max_schema
        # shard -> {int key -> 13-byte record}; a shard is an 8-day block of
        # authored days (key >> SHARD). No single table grows with the whole season:
        # MicroPython grows a dict by allocating a new table, and one big table
        # needed a large contiguous block late in the season (eight ships write
        # about a fifth more records than seven).
        self.recs = {}
        self.n = 0
        self.by_eff = {}    # effective day -> list of keys (unsorted)
        self.unknown = []   # newer-schema records: kept and relayed, never interpreted

    def __len__(self):
        return self.n

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
        sh = self.recs.get(k >> SHARD)
        if sh is None:
            sh = self.recs[k >> SHARD] = {}
        old = sh.get(k)
        if old is None:
            sh[k] = rec
            self.n += 1
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
            sh[k] = rec
            return REPLACED
        return STALE

    def effective(self, day):
        # Records taking effect on this day, in key order.
        ks = self.by_eff.get(day)
        if not ks:
            return []
        ks = sorted(ks)
        return [self.recs[k >> SHARD][k] for k in ks]

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
                r = self.recs[k >> SHARD][k]
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
        return [r for _, r in self._sorted()] + list(self.unknown)

    def _sorted(self):
        # (key, record) in key order: shards in order, keys in order inside a shard.
        for d in sorted(self.recs):
            sh = self.recs[d]
            for k in sorted(sh):
                yield k, sh[k]

    def digest(self):
        # Order-independent digest for adverts: sha256 over the sorted records.
        try:
            from hashlib import sha256
        except ImportError:  # pragma: no cover
            from uhashlib import sha256
        h = sha256()
        for _, r in self._sorted():
            h.update(r)
        return h.digest()[:4]

    def seq_vector(self, ships=8):
        # Highest sequence number seen per author ship: what status adverts carry.
        v = [0] * ships
        for sh in self.recs.values():
            for r in sh.values():
                s = R.ship(r)
                if s < ships:
                    q = R.seq(r)
                    if q > v[s]:
                        v[s] = q
        return v

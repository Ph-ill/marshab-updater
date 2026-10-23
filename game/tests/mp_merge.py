# MicroPython: a long sync's worth of records merged back to back must not fragment the
# heap into a MemoryError. ChoiceLog collects every GC_EVERY new records (lv/chlog.py).
# "nogc" turns that off: before the log was sharded and packed it failed here at 192k;
# now it passes without it too, and the collection stays as a margin for longer syncs.
#   micropython -X heapsize=192k tests/mp_merge.py [nogc]
import gc
import sys

sys.path.insert(0, ".")
from lv import record as R                    # noqa: E402
from lv.chlog import ChoiceLog, GC_EVERY      # noqa: E402

FLEET_KEY = b"test-fleet-key-not-secret"
off = "nogc" in sys.argv
with open("build/season_log.bin", "rb") as f:
    raw = f.read()
gc.collect()
log = ChoiceLog(FLEET_KEY)
if off:
    log.collect = None
n = len(raw) // R.LEN
for i in range(n):
    log.merge(raw[i * R.LEN:(i + 1) * R.LEN])
assert len(log) == n, (len(log), n)
if not off:
    assert log.gcs == n // GC_EVERY, (log.gcs, n)
# Merging again must be all duplicates and never collect (nothing new arrived).
before = log.gcs
for i in range(n):
    assert log.merge(raw[i * R.LEN:(i + 1) * R.LEN]) == 0
assert log.gcs == before
print("merged %d records, %d collections, digest %s" % (n, log.gcs, log.digest().hex()))
print("RESULT PASS")

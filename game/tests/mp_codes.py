# Crew-code checks under MicroPython (and CPython): same digest as the updater, and the
# lockout arithmetic with the board's wrapping tick counter.
#   micropython tests/mp_codes.py     (from game/)
import sys
sys.path.insert(0, ".")
from lv import codes as K  # noqa: E402

S = bytes(range(16))
assert K.digest(S, 0, "1234") == "0cc8d81bab788a28b5390ce71859e989a5b3e623b8e1cb44c6bfadccc5ff03e4"
b = K.CodeBook(K.make_config(["1234"] + [None] * 7, S))
assert b.check(0, "1234", 0) == (K.OK, 0)
for i in range(4):
    assert b.check(0, "0000", 5) == (K.WRONG, 4 - i)
st, wait = b.check(0, "0000", 5)
assert st == K.LOCKED and wait == 300, (st, wait)
assert b.check(0, "1234", 5 + K.LOCK_MS)[0] == K.OK
b.remember("ip|ua", 0, 3)
assert b.recall("ip|ua", 3) == 0 and b.recall("ip|ua", 4) is None
print("codes: ok on", sys.implementation.name)

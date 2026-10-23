# The 13-byte choice record that travels in adverts and over GATT.
#
#  byte 0   kind << 4 | schema
#  byte 1   author ship << 4 | delay (days until it takes effect: 1 normally, 3 out of range)
#  byte 2-3 sequence number, little-endian, per author ship
#  byte 4   authored flight day (1..42; 0 = setup)
#  byte 5-8 payload a, b, c, d (meaning depends on kind)
#  byte 9-12 tag: first 4 bytes of HMAC-SHA256(fleet key, bytes 0..8)
#
# Merge key: (authored day, ship, kind, sub). sub is payload a for votes and dilemmas
# (the card being answered) and 0 otherwise, so one ship can answer two open
# decisions on the same day. Same key: higher seq wins; equal seq: larger bytes win.
try:
    from hashlib import sha256
except ImportError:  # pragma: no cover
    from uhashlib import sha256

SCHEMA = 1
LEN = 13

ACTION = 1   # a = action (0 gift, 1 advice, 2 task, 3 rest), b = param, c = target crew, d = 0
VOTE = 2     # a = card index of the decision, b = option index
DILEMMA = 3  # a = card index of the dilemma, b = option index
NOTE = 4     # a = preset line (0..2), b = target crew

ADMIN_SHIP = 15  # outside the crew range 0..7; the author field is 4 bits (0..15)


def hmac_sha256(key, msg):
    key = bytes(key)
    if len(key) > 64:
        key = sha256(key).digest()
    key = key + bytes(64 - len(key))
    ipad = bytes([b ^ 0x36 for b in key])
    opad = bytes([b ^ 0x5C for b in key])
    return sha256(opad + sha256(ipad + bytes(msg)).digest()).digest()


def encode(fleet_key, kind, ship, delay, seq, day, a, b=0, c=0, d=0):
    body = bytes((
        (kind << 4) | SCHEMA,
        (ship << 4) | (delay & 15),
        seq & 255, (seq >> 8) & 255,
        day & 255,
        a & 255, b & 255, c & 255, d & 255,
    ))
    return body + hmac_sha256(fleet_key, body)[:4]


def valid(fleet_key, rec):
    return len(rec) == LEN and hmac_sha256(fleet_key, rec[:9])[:4] == bytes(rec[9:13])


def kind(rec):
    return rec[0] >> 4


def schema(rec):
    return rec[0] & 15


def ship(rec):
    return rec[1] >> 4


def delay(rec):
    return rec[1] & 15


def seq(rec):
    return rec[2] | (rec[3] << 8)


def day(rec):
    return rec[4]


def eff_day(rec):
    return rec[4] + (rec[1] & 15)


def key(rec):
    k = rec[0] >> 4
    sub = rec[5] if (k == VOTE or k == DILEMMA) else 0
    # Integer key sorts by authored day, then ship, kind, sub.
    return (rec[4] << 16) | ((rec[1] >> 4) << 12) | (k << 8) | sub

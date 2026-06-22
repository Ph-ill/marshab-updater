try:
    import os
except ImportError:
    os = None
try:
    import ubinascii as binascii
except ImportError:
    import binascii


def token_hex(nbytes=16):
    if os and hasattr(os, 'urandom'):
        return binascii.hexlify(os.urandom(nbytes)).decode('ascii')
    # Last-resort fallback for very small MicroPython builds.
    import random
    return ''.join('%02x' % random.getrandbits(8) for _ in range(nbytes))

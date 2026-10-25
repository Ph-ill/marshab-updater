# machine for the unix port: Pin("LED") counts its writes (tests/fakeboard/fakeboard.py).
# A count, not a list: the breathing light writes ~50 times a second while a pattern plays,
# and a list of them would grow into the heap the tests measure (tests/mp_sync_heap.py --led).
writes = [0]


class Pin:
    OUT = 1
    IN = 0

    def __init__(self, name, mode=None):
        self.name = name
        self.v = 0

    def value(self, v=None):
        if v is None:
            return self.v
        self.v = 1 if v else 0
        writes[0] += 1


def reset():
    raise SystemExit("machine.reset (fake board)")


def bootloader():
    raise SystemExit("machine.bootloader (fake board)")


def unique_id():
    return b"\xfa\x4e\xb0\xa2\x00\x00\x00\x01"

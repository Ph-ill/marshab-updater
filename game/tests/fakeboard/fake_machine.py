# machine for the unix port: Pin("LED") records its writes (tests/fakeboard/fakeboard.py).
writes = []


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
        writes.append(self.v)


def reset():
    raise SystemExit("machine.reset (fake board)")


def bootloader():
    raise SystemExit("machine.bootloader (fake board)")


def unique_id():
    return b"\xfa\x4e\xb0\xa2\x00\x00\x00\x01"

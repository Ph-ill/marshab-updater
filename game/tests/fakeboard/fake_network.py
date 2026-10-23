# network for the unix port: a hotspot that is "up" on 127.0.0.1 (tests/fakeboard/fakeboard.py).
AP_IF = 1
STA_IF = 0


class WLAN:
    def __init__(self, i):
        self.i = i
        self.on = False
        self.cfg = {}

    def config(self, **kw):
        self.cfg.update(kw)

    def active(self, v=None):
        if v is None:
            return self.on
        self.on = bool(v)

    def ifconfig(self):
        return ("127.0.0.1", "255.255.255.0", "127.0.0.1", "127.0.0.1")

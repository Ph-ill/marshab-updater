# Shared pin/ownership helpers: Hail need not retain Test-light playback code.
TEST_MS = 10000

def _pin(sh):
    f = getattr(sh, "led_pin", None)    # tests: a fake pin's factory
    if f:
        return f()
    p = getattr(sh.led, "pin", None)    # lvled.Led's own, once it has written
    if hasattr(p, "value"):
        return p
    from machine import Pin
    return Pin("LED", Pin.OUT)


def _hold(sh, let_go=False):
    # Keep lvled.Led (the Ship light, when on) dark and off the pin; let_go: look again now.
    l = sh.led
    if getattr(l, "enabled", False) and hasattr(l, "seq"):
        if l.lit:
            l._write(0)                 # (lit mid-pattern: dark now, not after the hold)
        l.seq = None
        l.mid = l.lit = 0
        n = l.clock.uptime()
        if let_go:
            l.next = n
        elif l.next < n + 500:
            l.next = n + 500


def _busy(sh):
    return (sh.ble is not None and sh.ble.busy()) or (sh.web is not None and sh.web.busy > 0)



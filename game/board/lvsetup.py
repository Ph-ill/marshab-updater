# Boot-only configuration; not retained while serving phones.
import lvship

def wanted(cfg):
    # Should the phone game be running? phone_game true, or "auto" on a firmware that has a
    # frozen core at all (shadowed or not: lvship.game_fw says no to a shadowed one).
    v = cfg.get("phone_game", "auto")
    if v != "auto":
        return bool(v)
    try:
        import lv
        return lv.firmware()[0] is not None
    except Exception:
        return False


def config(got, board=lvship):
    # cfg from the ship.json lvsafe.check() has just read and checked (got), not a second
    # read (a one-off read error there would give DEFAULTS: a fake ship 1, review #2 m1).
    # got None (lvsafe itself unusable): lvship.load_config() reads it, as 0.2.6 did.
    if got is None:
        return board.load_config()
    c = dict(board.DEFAULTS)
    if got:
        c.update(got[0])
    try:
        c["ship_id"] = min(8, max(1, int(c["ship_id"])))
    except (TypeError, ValueError):
        c["ship_id"] = 1
    return c




import os
import time


def boot(BOOT_WINDOW_MS, flag, safe_mode):
    print("boot: The Long Voyage starts in %d s (Ctrl-C or any mpremote command stops it)" % (
        BOOT_WINDOW_MS // 1000))
    time.sleep_ms(BOOT_WINDOW_MS)
    if flag("/data/safe"):
        print("safe: /data/safe found, not starting (remove it to play)")
        return
    try:
        os.stat("/data/maint")
        os.remove("/data/maint")
        print("maint: /data/maint found, not starting (once)")
        return
    except OSError:
        pass
    try:
        os.mkdir("/data")
    except OSError:
        pass
    trial = flag("ota/state.json")
    got = []
    try:
        import lvsafe
        why = lvsafe.check(trial, got=got)
    except Exception as e:  # lvsafe itself unusable (a damaged lvsafe.mpy): play as 0.2.6 did,
        print("safe: no boot check %r" % (e,))    # rather than crash-loop with no hotspot
        why, got = None, None
    lvship.drop("lvsafe")
    lvship.drop("lvledcfg")                    # (lvsafe asked it whether ship.json is whole)
    cfg = config(got)
    if why:
        safe_mode(cfg, why)
        return None
    try:
        import lv
        print("firmware: " + lv.describe())
    except Exception as e:
        print("firmware: %r" % (e,))
    print("lvship %s ship %d, free heap %d" % (lvship.VERSION, cfg["ship_id"], lvship.free()))
    return cfg, trial


def prepare(cfg):
    ap = None
    ip = "192.168.4.1"
    if cfg["hotspot"]:
        import lvwifi
        ap = lvwifi.hotspot(cfg)
        try:
            a = ap.ifconfig()[0]
            if a and a != "0.0.0.0":
                ip = a
        except Exception:
            pass
    game = cfg["hotspot"] and lvship.phone_game(cfg)
    days = None
    if game:
        import lvdays
        days = lvdays.Days("/data/days.bin")
    ship = lvship.Ship(cfg, days=days)
    return ship, ap, ip, game

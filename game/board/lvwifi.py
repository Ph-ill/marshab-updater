# The hotspot (SoftAP) for phones. Started before BLE, as on the coex bench.
# The password comes from /data/ship.json (8-63 characters); without one the AP uses the
# public placeholder below, so set one on every board that leaves the bench.


def hotspot(cfg, say=print):
    import network
    c = cfg
    try:
        import rp2
        rp2.country(c["country"])
    except Exception:
        pass
    ap = network.WLAN(network.AP_IF)
    pw = str(c.get("hotspot_password") or "")
    if c.get("hotspot_open"):
        pw = ""
    elif not 8 <= len(pw) <= 63:
        pw = "CHANGE_ME"
    ssid = "%s%d" % (c["ssid_prefix"], c["ship_id"])
    try:
        if pw:
            ap.config(essid=ssid, password=pw, channel=c["channel"])
        else:
            ap.config(essid=ssid, security=0, channel=c["channel"])
    except Exception as e:
        say("wifi: config %s" % e)
    ap.active(True)
    say("wifi: hotspot %s up" % ssid)
    return ap

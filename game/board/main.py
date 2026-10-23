# Boot: hotspot first, then the ship (BLE sync + story) and the status server.
# Put an empty file at /data/maint to skip this once (frees the REPL for mpremote).
import os

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import lvship


def main():
    cfg = lvship.load_config()
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
    print("lvship %s ship %d, free heap %d" % (lvship.VERSION, cfg["ship_id"], lvship.free()))
    if cfg["hotspot"]:
        import lvwifi
        lvwifi.hotspot(cfg)
    ship = lvship.Ship(cfg)

    async def run():
        if cfg["hotspot"]:
            await asyncio.start_server(ship.http, "0.0.0.0", cfg["http_port"])
        await ship.loop()
    asyncio.run(run())


main()

# Runs before main.py. Only does anything while an over-the-air update is pending or on
# trial (ota/state.json, written by lvota.py): then lvboot.py swaps it in, or counts the
# boot and arms the rollback deadline, or puts the old files back. Never sent over the air.
import os
try:
    try:
        os.stat("ota/state.json")
    except OSError:
        os.stat("ota/state.json.tmp")
    import lvboot
    if lvboot.run() != "trial":     # on trial it stays: its deadline timer is running
        import sys
        del sys.modules["lvboot"]
        del sys
    del lvboot
except OSError:
    pass
except Exception as e:
    print("boot: ota %r" % (e,))

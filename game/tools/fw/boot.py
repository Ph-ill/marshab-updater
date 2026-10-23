# Frozen boot.py of the Long Voyage game firmware. A frozen boot.py runs instead of one on
# the filesystem, so it does as little as possible: make /data, and if the filesystem
# has no main.py yet (a fresh board, or one wiped for the game firmware) write the
# one-line main.py that starts the frozen game. An existing main.py is never touched,
# so a release installed by the web updater (or the coex bench) still runs instead.
import os

try:
    os.mkdir("/data")
except OSError:
    pass
try:
    os.stat("/main.py")
except OSError:
    try:
        with open("/main.py", "w") as f:
            f.write("import lvmain  # the frozen game (lvmain.py); delete this file to stop it\n")
    except OSError:
        pass
del os

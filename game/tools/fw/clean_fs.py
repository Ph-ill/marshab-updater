# Run on a board with:  mpremote connect <PORT> run tools/fw/clean_fs.py
# Clears the board's filesystem before the game firmware's files go on (docs/BENCH_TEST.md,
# Variant B): the filesystem survives a .uf2 flash, and a leftover /lv folder would hide the
# frozen game core (every module back in the heap), and on lv-core 0.2.0 a leftover
# lvship.mpy ... or pack.bin would run instead of its frozen copy. Keeps /data (ship settings, the log,
# crew codes) and bench logs (*.csv, *.txt, *.old). Prints what it removed. The updater's
# install does the same cleaning itself; this is for the mpremote route.
import os

KEEP_DIRS = ("data",)
KEEP_EXT = (".csv", ".txt", ".old")


def rm(path):
    if os.stat(path)[0] & 0x4000:
        for name in os.listdir(path):
            rm(path + "/" + name)
        os.rmdir(path)
    else:
        os.remove(path)
    print("removed", path)


for name in os.listdir("/"):
    if name in KEEP_DIRS or name.endswith(KEEP_EXT):
        print("kept   ", "/" + name)
        continue
    rm("/" + name)
print("clean: now copy the game firmware's files (LAYOUT=fw sh tools/board_build.sh <PORT>) or install the release for this firmware from the updater page (0.2.0-lv-test on lv-core 0.2.0)")

# Run on a board with:  mpremote connect <PORT> run tools/fw/clean_fs.py
# Clears the board's filesystem for the game firmware (docs/BENCH_TEST.md, Variant B): the
# filesystem survives a .uf2 flash, and any lvship/lv module or main.py left on it would run
# instead of the frozen game. Keeps /data (ship settings, the log) and bench logs (*.csv,
# *.txt, *.old). Prints what it removed.
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
print("clean: reset the board (mpremote connect <PORT> reset); the game firmware writes /main.py and starts")

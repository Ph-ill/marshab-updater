# The game firmware's runtime half of lvfrozen.py (tools/fw/gen_lvfrozen.py appends this
# file after the generated constants; both are frozen, so none of it costs heap).
# lv/__init__.py calls overrides() at import: lvx/<name>.mpy|.py on the filesystem replaces
# the frozen lv.<name> without reflashing (the updater's partial releases ship these).

# Load order: a module's lv imports come before it.
ORDER = ("ops", "prng", "record", "pack", "state", "chlog", "clock", "codes", "led",
         "engine", "engage", "sync", "ble")


def overrides(g, d="lvx"):
    """Load lvx/ overrides into the lv package (its globals g); -> names replaced."""
    done = []
    # Relative, like the '' entry on sys.path: the board runs from /, the tests from a folder.
    try:
        import os
        names = os.listdir(d)
    except Exception:          # no override directory: nothing to do
        return done
    import sys
    mods = []
    for fn in names:
        for ext in (".mpy", ".py"):
            if fn.endswith(ext) and not fn.startswith("_"):
                n = fn[:-len(ext)]
                if n not in mods:
                    mods.append(n)
    mods.sort(key=lambda n: (ORDER.index(n) if n in ORDER else len(ORDER), n))
    sys.path.insert(0, d)
    try:
        for n in mods:
            if n in sys.modules:   # a top-level module of that name is already loaded
                continue
            try:
                m = __import__(n)
            except Exception as e:  # a broken override falls back to the frozen module
                print("lv: override %s failed (%r), using the built-in one" % (n, e))
                sys.modules.pop(n, None)
                continue
            sys.modules["lv." + n] = m
            del sys.modules[n]
            g[n] = m
            done.append(n)
    finally:
        sys.path.pop(0)
    return done


def firmware():
    """The frozen core: {id, version, core, modules, shadowed}."""
    import os
    import sys
    core = {"id": ID, "version": VERSION, "core": CORE, "modules": list(MODULES),
            "shadowed": False}
    # A lv/ folder in a sys.path entry searched before the frozen modules hides the
    # frozen package: then every module comes from files and costs heap.
    for p in sys.path:
        if p == ".frozen":
            break
        try:
            os.stat((p + "/" if p else "") + "lv")
            core["shadowed"] = True
            break
        except OSError:
            pass
    return core


def describe(ov):
    c = firmware()
    if c["shadowed"]:
        return "frozen %s %s (core %s) HIDDEN by a /lv directory: remove it" % (
            ID, VERSION, CORE)
    return "frozen %s %s (core %s), overrides: [%s]" % (ID, VERSION, CORE, ", ".join(ov))

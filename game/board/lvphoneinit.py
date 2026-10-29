# Phone construction is needed once, not throughout every streamed response/update.
from lv import codes as K
from lv import engage as EN
from lv.state import N
from lvphone import MAX_TOKENS

def setup(self, ship, root="", say=print):
    self.ship = ship
    self.root = root
    self.say = say
    self.data = ship.data
    self.book = K.load((self.data or "data") + "/crew.json")
    self.tokens = []          # [token, crew], oldest first
    self.etable = EN.load_table(root + "engage.bin")
    self.eng = EN.Engage(self.etable, ship.pack.voyage_key, ship.pack.season)
    self.local = None
    try:
        with open(self.data + "/local.bin", "rb") as f:
            self.local = EN.Local.load(f.read())
        if self.local.season != ship.pack.season:
            self.local = None
    except Exception:
        pass
    if self.local is None:
        self.local = EN.Local(ship.pack.season)
    say("phone: codes set for %d of %d, %d phones max" % (
        sum(1 for c in range(N) if self.book.is_set(c)), N, MAX_TOKENS))

    # Include construction's temporary code/data in board heap probes too.
    import lvweb
    if lvweb.probe:
        lvweb.probe()

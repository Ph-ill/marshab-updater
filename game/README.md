# The Long Voyage: game core

This is the hardware-independent core of the game that runs on the eight Pico W Starships.
The same Python runs on CPython 3 (PC simulator and tests) and on MicroPython 1.29 (the boards).
It uses integer maths only, fixed-size bytearrays, and has no dependency on Wi-Fi or BLE.
The design Page is the spec; this folder is the first build of it.

```
lv/          the core (this is what goes on the Pico)
  prng.py      xorshift32 + per-day seed from the voyage key
  record.py    13-byte signed choice record
  chlog.py     choice log: set-union merge, effective-day index, ballots
  ops.py       opcodes shared by the compiler, engine and renderers
  pack.py      loads build/pack.bin (logic only, no text)
  state.py     ship state + canonical dump/digest (snapshots)
  engine.py    the daily tick
content/     story source: fleet.lv, system.json, cards/*.lv
tools/lvc.py compiler + validator (CPython only) -> build/pack.bin, text.json(.gz), text.dev.json
sim/         PC season simulator, Python renderer, sample output in sim/out/
web/render.js  phone-side renderer (the Pico never builds sentences)
tests/       unit tests, MicroPython replay check, JS-vs-Python renderer check
bench/coex-test/  Wi-Fi + BLE coexistence bench firmware (as published in 0.0.2-coex)
```

## Run it

```bash
sh game/tests/run.sh                                  # everything below, in order
python3 game/tools/lvc.py                             # compile + validate the pack
python3 game/sim/season.py                            # 42-day season, narrative, stats, determinism
python3 game/sim/season.py --seasons 300              # balance + fair-play check (exits 1 if a season misses a core clue)
python3 game/sim/season.py --spoilers                 # also print ending ids (output is spoiler-free by default)
MICROPYTHON=/path/to/micropython game/tests/run.sh    # also replays the season under MicroPython
```

`season.py` also writes `sim/out/epilogue.txt`: one closing line per crew member,
from `epi.story` in system.json (lvc turns card ids into indices). The web end
screen should mirror `Renderer.epilogue` in sim/render.py.

## Phone UI prototype

```bash
python3 game/tools/lvc.py && python3 game/web/build.py   # build/app.html.gz: the one page the Pico serves
python3 game/sim/mockserver.py --day 8                   # mock Pico on http://localhost:8042/
```

Open it at phone width (360-430 px). Add `?day=N` to jump to another flight day (mock only). The mock runs the real engine on the simulated season. The page sees only what this ship has heard by gossip, and your taps become signed records that take effect the next day. `web/shots.sh OUTDIR` builds the page, starts the mocks and takes chrome-less screenshots of every screen at 390x844 and 360x800. `SIZES=cna web/shots.sh OUTDIR` uses the captive-sheet sizes below instead and writes `OUTDIR/cna-WxH/NAME.png`. Both need `PW` (a playwright-core directory) and `CHROME`.

* **One file.** `web/app.html` holds the CSS, the JS and the SVG. `web/build.py` inlines `web/render.js`, strips comments and gzips the result. It comes to about 13.8 KB gzipped (budget 128 KB), plus `text.json` (about 2.3 KB gzipped, fetched separately so a new story pack doesn't need a page rebuild).
* **Nothing is stored on the phone.** There's no localStorage and no cookies; the captive sheet would wipe them anyway. You tap your name and enter your 4-digit crew code. The session token lives in page memory.
* **Crew codes are set by Phill, up front.** The updater's ship setup writes `data/crew.json` (a fleet salt and a salted sha256 per person, the same on all eight ships), so nobody can claim a name by tapping it first. Five wrong codes for a name lock that name for 5 minutes, timed by the board, not the phone. A name with no code shows "Not set up" and can't be picked. See `lv/codes.py`.
* **The ship remembers your phone for the day.** After a good code, the ship keeps (phone IP + User-Agent, crew, flight day). Reopening the captive sheet the same flight day goes straight to your ship (`GET /api/me`). The next day, or after "Sign out" on your astronaut's page, it asks again. The first sign-in since the board started shows the "Welcome aboard" astronaut card; after that you go straight home.
* **Live updates.** The page opens a WebSocket at `/ws` that announces a new version. If it can't connect, the page polls `/api/v` every 15 s and says so in a one-line banner.
* **Privacy.** A private dilemma's text is shown only to the person who looks after that astronaut. Everyone else's log just says a private message arrived.
* **Dark mode is automatic.** `prefers-color-scheme: dark` swaps the paper and ink colours. There's no switch on the page; it follows the phone. `shots.mjs` renders `13-home-dark` and `14-log-dark` at every size.
* **Late signals.** Nearly every day is re-run once, the next day, as yesterday's taps arrive. The page treats that as normal ("Today · may still change", "Yesterday · may still change"). It only adds a one-line "Log updated FD xx · a late signal re-ran this day" note when a day changed two or more days later.

### Captive sheet sizes

On an iPhone, the page opens in the captive network assistant (the "Log in" sheet that pops up when you join the hotspot), not in Safari. It's smaller than a Safari page. It's a sheet with its own Cancel/Done bar and no Safari toolbars, has no persistent cookies, and gives `alert()`/`confirm()` no reliable dialog. Apple doesn't publish the sheet's size, so the layout is checked at these estimated CSS viewports (`SIZES=cna`):

| Size | Stands in for |
|---|---|
| 320x480 | iPhone SE with Display Zoom: the worst case |
| 375x580 | iPhone SE 2nd/3rd gen |
| 375x700 | iPhone 12/13 mini |
| 390x730 | iPhone 12-16 |
| 360x600 | Android, captive portal login under its 56 dp header |

Each is the screen, less the status bar, the gap above the sheet and a ~56 px Cancel/Done bar. These are estimates, not measurements. To measure a real phone, open the sheet with `?probe` on the URL. A strip shows `innerWidth x innerHeight`, the visual viewport, the safe-area insets, the device pixel ratio, and whether the page thinks it's in the iOS sheet (a User-Agent without `Safari/`), Safari or an Android WebView.

Below 640 px of height the page uses a tighter layout: 52 px keys and buttons (above Apple's 44 pt minimum), a 44 px top bar, and a slimmer dock. Below 520 px it also drops the sign-in help line. The keypad is on the page, so the iOS keyboard never opens and never covers anything. Send errors appear as a strip in the dock, not an `alert()`.

The `game/` folder is not part of the updater image. The Dockerfile copies only the web app and `firmware/`.

## How the pieces fit

The story is a pure function: **story = f(pack, voyage key, choice log)**.

* **Choice log.** Every player choice becomes a 13-byte record:
  `kind<<4|schema, ship<<4|delay, seq u16 LE, authored day, a, b, c, d, HMAC-SHA256 tag[:4]`.
  * Records merge as a set union keyed by `(day, ship, kind, sub)`. `sub` is the card for votes and dilemmas, so one ship can answer two open items on the same day.
  * When two records share a key, the higher seq wins; on equal seq, the larger bytes win. Order and duplicates therefore never matter.
  * Records with an unknown (newer) schema are kept and relayed, but never interpreted.
* **Effective day.** A record takes effect on `authored day + delay`. The delay is 1 normally, or 3 if the author was out of range on both that day and the day before. Late records are normal: a ship that hears one for a day it has already simulated reloads its last weekly snapshot (about 320 B) and replays forward.
* **Votes and dilemmas.** These close at a fixed day and resolve with whoever voted. Nothing waits for anyone:
  * No ballots: the crew's lean decides (the fleet's summed trait on the card's axis).
  * Ties: the lean breaks the tie.
  * Private dilemmas: if the owner didn't answer, the astronaut picks in character.
  * Rescues: one tap from anyone is enough, otherwise a default applies.
* **Inactive astronauts act on their own.** Each astronaut does what its player instructed today (gift / advice / task / rest). If there was no instruction, it picks something from its traits. A player who never opens the page still gets a crew member with a story.
* **Daily tick order.** Each day runs these steps in order:
  1. Records in effect today.
  2. Close the decisions that are due.
  3. Each astronaut acts.
  4. Wandering between ships.
  5. Consumption.
  6. Due callbacks.
  7. One event (55%).
  8. A fleet decision (50%, if none is open).
  9. A private dilemma (35%; max 2 per player per season, each card once per player).
  10. Two beats (60% each).
  11. On day 42, the first ending whose conditions pass.
* **Story output.** The output is 8-byte entries `[day, code, card, a, b, c, d, e]`. The phone renders them with `text.json`. Each day's entries are folded into an 8-byte hash chain in the state, so snapshots don't grow over the season.

## Results (build 0.1.0, 15 sample cards)

*Current content pack (217 cards):* pack.bin 6,752 B, text.json 24,777 B gzipped (card ids are left out of the shipped file; `build/text.dev.json` keeps them for sim/ and the tests), peak MicroPython heap 71,104 B on the 64-bit unix port (51,984 B on a 32-bit build, like the Pico's), snapshot 743 B, final reference digest `651a9ce252fb4b8d` (authored and reversed merge order). The reference season authors 274 records from 8 simulated players (2 never play), 60 of them crewmate gifts; without the gift records the digest is `24751f12277fc052`, the content-voice figure, so gifts are the only difference. The choice log packs its records (one bytearray per 8-day shard, lv/chlog.py), which is what keeps the extra records under the 80 KB line. On a 32-bit build the whole check runs in a 92 KB heap from .py (80 KB from .mpy: compiling engine.py is the peak); the 64-bit port needs 136 KB from .py, 96 KB from .mpy. The deepest replay in the four delivery scenarios rewrites 12 days, and a ship cut off for a long stretch can need up to about 30. `python3 -m unittest discover -s tests` runs 163 tests (103 content, 23 core, 37 engagement). The figures below are the original 15-card measurements.

**Determinism.** The reference season authors 170 records from 5 simulated players; 2 never play and one is out of range for days 15-21. Those records are then delivered to 8 independent ships in 4 ways:
* instant;
* gossip (0-2 days of lag);
* reverse-order with 20% duplicates;
* bursty, with one ship's links down every 5 days.

Every ship ends on the same reference digest in every scenario (`8782c95070c3682d` for the 15-card pack; the current pack's digest is above). The deepest replay rewrote 11 days.

**MicroPython.** `tests/mp_check.py` runs under a v1.29.0 unix-port build (both 64-bit and 32-bit `-m32`, the same word size as the RP2040). It replays the log merged in authored and reversed order. All 42 per-day digests match CPython, and the final digest matches (`8782c95070c3682d` then; see above for the current pack).

**Size and RAM** (32-bit MicroPython, `gc.mem_alloc`):

| | 15 cards (measured) | ~110 cards |
|---|---|---|
| pack.bin | 575 B (≈33 B/card) | ≈3.7 KB |
| pack in RAM | 2.4 KB | 13.8 KB (measured on a 110-card synthetic pack) |
| text.json / .gz (phone) | 4.2 KB / 2.0 KB | ≈20 KB / ≈9-10 KB (estimate, real prose) |
| core code in RAM | 19 KB as .mpy, 20.6 KB from .py | same; ≈0 if frozen into the firmware |
| choice log | 3.9-4.9 KB for 169 records (≈23-29 B/record) | ≈10 KB for 8 active players; ≈25 KB worst case |
| state + engine | ≈1.1 KB, snapshot about 320 B (737 B with the current pack) | same |
| whole check, peak | runs in a 56 KB heap (.mpy); 68 KB with the current pack | ≈50-60 KB of the 157-168 KB free with coex running |

**Tick time** (x86 unix port, 32-bit): the 15-card pack averages 0.16 ms/tick (worst 0.28 ms); the 110-card pack averages 1.3 ms (worst 2.9 ms). A record merge with its HMAC check takes about 15 µs.

*Pico estimate* (×30-60 for a 133 MHz M0+, not yet measured on a board):
* About 40-80 ms per tick (worst about 0.1-0.2 s) with 110 cards.
* A 12-day late-record replay takes about 0.5-1 s. That is fine as a background job between radio windows.
* A record merge takes about 0.5-1 ms.

## Design questions raised by the build

1. **Out-of-range votes can miss the close.** A ballot counts if it was authored while the vote was open and takes effect by close. A voter on delay 3 who votes on the last day misses it. Options: accept it, or count a ballot by authored day and let a late close re-resolve the vote by replay. Replay already makes the second option possible.
2. **The merge key includes `sub`.** The Page says `(ship, day, kind)`. With two decisions open, a ship needs two VOTE records on one day, so the key is `(day, ship, kind, sub)`.
3. **The "a late signal changed this" marker is ship-local.** A replay can rewrite up to about 12 days of a story the phone has already shown. The core is deterministic, but the page needs a policy: show a "the log was updated" note, or only show days older than N as final.
4. **32-bit PRNG on the RP2040.** xorshift32 values exceed MicroPython's 31-bit small ints, so some steps allocate bigints. This works and matches on the 32-bit build. If tick time on the board is tight, split the state into two 16-bit halves.
5. **The crew roster is real and lives in `content/roster.lv`.** Phill (ship 1, flagship), Jacques, Kim, Jai, Michelle, Diego, Dorian, Marco (ship 8). No quirks were given, so each astronaut's starting traits are seeded from the voyage key and their name; add `quirk <name>` to a line to set one. Each line also carries up to four `habit "..."` entries (the player's own light quirks); `each habit N` cards clone once per crewmate who has an Nth habit, so a quirk line only ever renders for its owner (see `content/STYLE.md`, "The habit slot"). The compiler rejects gendered pronouns in any card or template text, and story beats are kept good-natured (injuries come from the environment, never from someone's mistake).
6. **Content: the first voice batch is in (91 cards).** See `content/STYLE.md` for the house style. Card language additions: `hook` (a cliffhanger that is the last line of its day, at most one every 4 days, resolved the next day by a `due` card with `when fired <hook>`; text.json marks hooks with `"h":1` so the phone can show them as "Last night...") and `when tag A <word>` (roster tags, compiled to a crew bitmask). `lvc` also prints `style:` warnings: hard-coded names, name-checked jobs, demeaning words, cheap resolutions, calendar pins, over-long text. `tests/test_content.py` keeps the real pack at zero style warnings.
7. **Content batch 2 (113 cards).** Every card carries `cat <category> [skill]`; `lvc` prints the mix and fails the build if repairs exceed 25% or skill flavor 18% (`check_mix`). `check_ramp` enforces the slow burn (no uncanny vocabulary before day 11, uncanny hooks only from day 25; see STYLE.md). `clue` marks a card for the second read: text.json gains `"reread": [card indices]`, and the end screen (web, not yet built) should list those cards' flight days under the ending without explanation. The story design is in `content/STORY_BIBLE.md` (spoilers; players should not read it). Engine: role casting prefers the least-featured crew (`State.spot`, part of the snapshot), keeping story appearances within about 2% of the mean over 100 seasons. Every ending lands in 8.7-25.7% of 300 seasons (26 to 77 of 300 each).
8. **The weekly snapshot cadence is a guess.** Snapshots take about 737 B each with the current pack, so daily snapshots on flash would make replays almost free.

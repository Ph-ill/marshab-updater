# Settings, Test light, Change your code and Reset this ship

Every signed-in screen has a gear at the top right of the top bar, after the battery and
the flight day. It's a line icon drawn like the tab icons (20 px, 1.5 px strokes), with a
44 × 44 px tap target that doesn't make the bar taller, and the label "Settings" ("Settings,
update ready" with a rust dot when an update is waiting). It opens one page for this phone
and this ship (`web/settings.js`, `web/settings.css`; route `#set`). The four tabs stay as
they are, with none marked current.

On Android, a Full screen button (four corners, the same size) sits just before the gear;
it isn't part of Settings (docs/OTA.md section 6, "Full screen on Android").

The crew page is only about the crew now: your astronaut, crewmates and "How to play"
(when there's no FILE tab). Ship software, Add to home screen, the Ship light and Sign out
moved here. The old `#sw` and `#a2h` routes open Settings.

## Sections, top to bottom

1. **Ship software** (`web/ota.js`, `otaSect()`): installed, channel, available, last
   checked, and the **Install** and **Check for updates** buttons. While an install runs,
   and for its outcome, Settings shows only the install screen (`otaScreen()`). The home
   screen's update notice still has **Install** and **Later**; Install opens Settings with
   the progress.
2. **Home screen icon** (`web/a2hs.js`): the steps for the browser you're in. In a browser
   that can't add one, or once the game runs from the icon, it says so instead.
3. **Ship light**: the LED notifier switch (`POST /api/led`), and under it **Test light**
   (below). Shown when the ship reports one (`S.led` isn't null).
4. **Battery** (`web/batt.js`): charge, voltage and whether it's charging. Only on a ship
   with a battery (`S.bat`).
5. **This phone**: **Sign out**.
6. **Your code**: **Change your code** (below).
7. **Reset this ship**, last, styled as a danger action (a rust border and rust text, under
   a rust rule).

## Test light

So you can see a ship's LED works without opening the case, whether the Ship light is on
or off.

**On the phone.** Under the Ship light switch, a secondary button: **Test light · about 4 s**,
with "Three blinks, then one slow pulse. Works with the light off too." under it. Tapping
it shows **Testing… · watch LV-N** at once (disabled, `aria-busy`), "Look at LV-N now: three
blinks, then one slow pulse.", and a thin rust bar along the button's foot that fills for
exactly as long as the ship says it plays (`ms` from the answer; no bar with reduced
motion). Then it's back to **Test light**, with "Finished. The light is back to on/off."
Only that row is repainted (`ledtPaint()`), never the whole page, so a half-typed code in
Your code is kept. A tap while it plays does nothing; a refusal from the ship shows in rust
under the button.

**On the ship.** `board/lvledtest.py` (`start()`, `play()`), routed from `board/main.py`'s
`ota_route` as `POST /api/led/test`, loaded per request and dropped, so it ships over the air
and the frozen core (`lvled`, `lvledcfg`, `lvweb`, `lvphone`) is unchanged. The pattern is
its own asyncio task, about 4 s (`TEST_MS` = 4000):

| ms from the tap | the LED |
|---|---|
| 0–1500 | three blinks, 250 ms fully on, 250 ms off (one pin write each edge) |
| 1500–1800 | dark |
| 1800–4000 | one breath, 1 s up and 1.2 s down: software PWM in 10 ms frames as `lvled.py` breathes, lit (x/100)² of each frame |
| 4000 | dark; the light goes back to what it was doing |

Every edge is an `await`, except a dim on-part under 1.5 ms (a short busy-wait, as in
`lvled.py`), so the web server, the DNS, the BLE sync and the charger watch (every 100 ms)
all keep running. While a BLE sync or an HTTP request is in progress, the breath plays as a
plain blink through its bright middle, as `lvled.py` does.

With the Ship light on, `lvled.Led` is held dark for the test: its pattern dropped and its
next look pushed past the test, refreshed every frame, so only one of them ever writes the
pin. At the end it's let go and looks again at once. Its gift, new-day and waiting flags,
quiet hours and budget are untouched. With the light off, the test drives the LED pin on
its own (`machine.Pin("LED")`, or `lvled.Led`'s pin once it has one) and leaves it dark.

| Answer | When |
|---|---|
| 200 `{ok, ms}` | started |
| 401 | no session, or a stale token |
| 404 | not a POST |
| 429 `{ms}` | a test is already playing; `ms` left, nothing else plays |
| 500 | no LED to drive (no `machine.Pin`), nothing left running |

A pin that fails mid-pattern ends the test (logged), and the next tap is taken. A test that
somehow never finished stops blocking taps 5 s after it should have ended.

## Change your code

Your crew code is the 4 digits you sign in with. Everyone starts with the same code on
all eight ships (`tools/bench.py --code` writes it, or the updater's ship setup). Settings
lets you change yours on the ship you're connected to.

**On the phone.** Tap **Change your code**. The form asks for **Your code now**, then
**New code** and **New code again**. All three use the numeric keypad, are masked, and
take only digits; a field moves on after 4 digits and Enter moves on or saves. The page
checks first, without asking the ship: every field must be 4 digits, the two new codes
must match ("The two new codes don't match. Type them again."), and the new code must
differ from the current one. Then it sends `POST /api/code {"old": "....", "new": "...."}`
with its crew token. On success it says "Done. Sign in on LV-N with your new code from now
on. You're still signed in here." **Cancel** closes the form; leaving Settings clears it.

**Only this ship changes.** The other seven keep your old code. A later `bench.py --code` for
you, or the updater's ship setup writing all the codes, puts a code back over yours
(`bench.py --code` for someone else keeps yours).

**On the ship.** `board/lvcode.py` (`change()`), routed from `board/main.py`'s `ota_route`
next to `/api/reset`, imported per request and dropped afterwards, so it ships over the air,
holds no RAM between requests, and the frozen core (`lvcodes`, `lvphone`, `lvweb`) is
unchanged. It goes in `gen_lvfrozen` `BOARD` and `tools/fw/manifest.py` for the next core.
Refusals, in this order, with nothing written:

| Status | When | Message |
|---|---|---|
| 404 | not POST | |
| 401 | no signed-in crew token | |
| 400 | a body that isn't a JSON object | |
| 400 | the new code isn't exactly 4 ASCII digits (sign-in's format) | "Your new code needs to be 4 digits." |
| 400 | the current code isn't 4 digits | "Your current code is 4 digits." |
| 400 | the new code is the same as the current one | "Your new code is the same as your current one." |
| 403 `{left}` | the current code is wrong | "That isn't your current code." |
| 429 `{wait}` | too many wrong tries | "Too many tries." |
| 409 | no code set for you on this ship | |
| 500 | the file couldn't be written | "The ship couldn't save it. Your current code still works." |

The current code is checked with the same `CodeBook.check` sign-in uses, so wrong tries
count against the same 5 tries and 5-minute pause as sign-in, per crew member: guessing
here doesn't get extra tries, and a pause from either blocks both. Nothing checks whether
another crew member already has the new code: sign-in is by name, then code, so two people
may share one, and refusing it would tell you someone else's code.

On success the ship works out the new digest (sha256 of the salt, your crew byte and the 4
digits, as `lv/codes.py`) and swaps only your digest in `/data/crew.json`'s own text, so
every other byte, everyone else's entry included, stays the same. The write is atomic:
`crew.json.new`, read back and checked, then renamed over `crew.json` (a rename that fails is a failure; 0.2.5/0.2.6 moved the old
file to `crew.json.old` first, and `board/lvsafe.py` still puts one back from there). On
any failure the `.new` is removed and the old file is left as it was. Then the in-memory
code book changes, so the new code works at once and your session stays. The ship never
logs or prints a code.

**Reset this ship** keeps `crew.json`, so a changed code survives a reset.

**The boot check (0.2.7, `board/lvsafe.py`).** Every boot reads `ship.json` and
`crew.json` before the game starts:

- A file that reads back and is usable is kept as it is. Its `.bak` copy is rewritten only
  when its contents differ (compared as data, not as text), so a normal boot writes
  nothing. A leftover `.new` or `.old` next to a good file is removed.
- A file that can't be read (a flash error) is read once more after a short pause. Still
  unreadable, missing or unusable: it is put back from, in order, `.new` (a write that
  had got as far as the rename, renamed into place), `.bak` (copied via `.bak.new`, then
  renamed) and `.old` (renamed), whichever is the first good one, and the boot says which.
- Nothing good to put back: the ship stays off (no hotspot, no game) and says so, and looks
  again every few minutes; the updater over USB fixes it. The one exception is a bench
  board: with no `crew.json` (nor its `.bak`, `.new` or `.old`) anywhere it has never been
  provisioned, so a missing or plain-JSON `ship.json` plays on the defaults. A board with
  crew codes never runs on defaults, so it can't come up as ship 1 under the default
  hotspot.

## Reset this ship

It's for starting a ship over, for example to try the first-time flow again, without
opening the case or a USB cable.

**On the phone.** Tap **Reset this ship**, then type the ship's number (the N in its Wi-Fi
name, LV-N). **Reset** stays off until the number matches. The page sends
`POST /api/reset {"confirm": N}` with its crew token. When the ship says yes, the page:

- clears this browser's storage for the ship's address (`localStorage.clear()` and
  `sessionStorage.clear()`: `lv.a2hs`, `lv.ota` with any downloaded update, `lv-briefed`,
  and the rest);
- drops its session;
- shows "Starting over";
- waits for the ship to answer again, then reloads to the sign-in.

**On the ship.** The endpoint is in `board/main.py` (`reset_ship`, routed next to
`/api/ota*`), so it ships over the air and the frozen core (`lvweb`, `lvphone`) stays as it
is. There's no other way in:

- not POST: 404;
- no signed-in crew token: 401;
- no `confirm`, a `confirm` that isn't this ship's `ship_id`, or a body that isn't JSON:
  403.

Nothing changes on a refusal. On success the ship answers 200 `{ok, restart_ms}`. A second
later it deletes the files and restarts (`machine.reset()`). There's no await between the
deletes and the restart, so nothing can write a file back in between.

**Deleted from `/data`** (`main.RESET`):

| File | What it is |
|---|---|
| `log.bin` | every record this ship holds: taps, votes, answers, gifts (other ships in Bluetooth range sync their own records back) |
| `days.bin` | the days told so far |
| `clock.json` | the saved time and flight day (the launch date in `ship.json` brings the day back as soon as a phone tells the time) |
| `local.bin` | what phones opened and saw (daily drops) |

Sign-ins and sessions (crew tokens, remembered phones, who has signed in since boot) live
in RAM only, so the restart forgets them. The funnel's seen-phones store goes in
`main.RESET` once it exists.

**Kept:**

- `/data/ship.json`: identity, hotspot password, `ota_src`, launch date, the Ship light;
- `/data/crew.json`: the crew codes;
- `/data/ship.json.bak` and `/data/crew.json.bak`: the boot check's last good copies
  (0.2.7, `board/lvsafe.py`), rewritten only when the file really changed;
- `/data/maint` and `/data/safe`;
- the installed software;
- `ota/`: the update state and the rollback copy.

## Tests

- **`tests/test_code.py`**, on CPython, MicroPython and the game firmware's unix build:
  - no session or a stale token: 401; GET: 404; not JSON: 400;
  - bad formats (3 or 5 digits, letters, non-ASCII digits, numbers instead of strings,
    missing fields): 400, file unchanged;
  - the same code: 400;
  - a wrong current code: 403 with the tries left, then 429 after 5, and sign-in paused too
    (and the other way round);
  - success: 200, the new code signs in and the old one doesn't, the session still works,
    and every other byte of `crew.json` is the same;
  - a failed write, read-back or rename: 500, `crew.json` unchanged, no `.new` left, the old
    code still works;
  - a code another crew member has: allowed;
  - nothing printed; `tools/bench.py --code` afterwards sets the named code, keeps the
    changed one and prints no codes.
- **`tests/phone_heap.py --ota`** changes a code and back on the frozen build inside the
  heap check (board peak under 80,000 B).
- **`tests/test_ledtest.py`**, in real time on a fake pin, on CPython, MicroPython and the
  game firmware's unix build:
  - GET: 404; no session or a stale token: 401, nothing played;
  - the pattern: three blinks of ~250 ms fully on, the dark gap, a breath that swells and
    fades (software PWM: 100+ short pulses), dark at the end, done in about 4 s;
  - a second tap while it plays: 429 with the ms left, and nothing more plays; a new tap
    after it ends plays again;
  - the event loop stays free: a 100 ms ticker is never more than 60 ms late, and
    `main.py`'s own `charger_watch` catches the charger plugged in mid-test;
  - with the Ship light on (`lvled.Led`, a gift waiting): the notifier never writes during
    the test, then its gift pulses come back, still on, the gift still waiting;
  - a busy radio: the breath as a plain blink;
  - no `machine.Pin`: 500, nothing running; a pin failing mid-pattern: the test ends,
    said so, and the next tap is taken; `lvledtest` dropped after each request; other
    paths (including `/api/led`) still reach the game.
- **`tests/phone_heap.py --ota`** taps Test light twice (a tap meanwhile refused) on a
  counted pin on the frozen build inside the heap check (board peak under 80,000 B).

- **`tests/test_reset.py`**, on CPython, MicroPython and the game firmware's unix build.
  The endpoint refuses, with no restart and every file byte-for-byte the same, when there's:
  - no session, or a stale token;
  - no confirm, or no body;
  - a wrong ship number;
  - a confirm that isn't a number, or a body that isn't JSON;
  - a GET.

  On success it answers before deleting anything, then deletes exactly the four files and
  restarts. `ship.json`, `crew.json`, `main.py`, the page and `ota/` stay untouched. A second
  reset is fine too, and other paths still reach the game.
- **`tests/app_e2e.mjs`**, against the board's own server on CPython and the frozen build:
  - the gear;
  - the section order;
  - the crew page without the moved rows;
  - `/api/reset` returning 401 without a session, 403 without the confirm and 403 with
    another ship's number, with the phone still signed in afterwards;
  - `/api/code` returning 401, 400 and 403, then the form changing the code: the old code
    refused, the new one signing in, and back again.
  - Test light: the button showing Testing, `/api/led/test` 429 meanwhile and 401 without
    a session.
- **`web/shots_settings.sh`**, against the mock (`sim/mockserver.py` `/api/reset`):
  - the gear's label, size and place;
  - every section;
  - the Ship light from Settings, and the battery facts;
  - the refusals, and the typed confirm (off for a wrong number);
  - after a reset: storage empty, the old token refused, back at the sign-in, and the
    first-time flow on the next sign-in;
  - Sign out;
  - Test light: under the switch, with the light off and on; Testing, the bar, the 429 for
    a tap meanwhile, back after about 4 s, repainted in place; it fits at 320 px;
  - Change your code: the row, the form, mismatched, short and same codes refused on the
    phone, the ship's refusals, a wrong code with the tries left, success, Cancel;
  - a ship with no battery or OTA at 320 px, and the top bar fitting at 320 px with the
    battery.

  It saves screenshots with placeholder story text.

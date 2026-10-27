# Settings and Reset this ship

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
3. **Ship light**: the LED notifier switch (`POST /api/led`). Shown when the ship reports
   one (`S.led` isn't null).
4. **Battery** (`web/batt.js`): charge, voltage and whether it's charging. Only on a ship
   with a battery (`S.bat`).
5. **This phone**: **Sign out**.
6. **Reset this ship**, last, styled as a danger action (a rust border and rust text, under
   a rust rule).

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
- `/data/maint` and `/data/safe`;
- the installed software;
- `ota/`: the update state and the rollback copy.

## Tests

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
    another ship's number, with the phone still signed in afterwards.
- **`web/shots_settings.sh`**, against the mock (`sim/mockserver.py` `/api/reset`):
  - the gear's label, size and place;
  - every section;
  - the Ship light from Settings, and the battery facts;
  - the refusals, and the typed confirm (off for a wrong number);
  - after a reset: storage empty, the old token refused, back at the sign-in, and the
    first-time flow on the next sign-in;
  - Sign out;
  - a ship with no battery or OTA at 320 px, and the top bar fitting at 320 px with the
    battery.

  It saves screenshots with placeholder story text.

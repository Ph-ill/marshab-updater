# Engagement layer (branch `engagement`)

Small, optional reasons to open the page each day. None of it can block the fleet or
punish anyone who doesn't play: three of eight crews can never play and the season still
runs (`tests/test_engage.py`, inactive season). Nothing is stored on the phone.

| Piece | Where | Shared via BLE? | Affects story/digest? |
|---|---|---|---|
| Daily drop | `lv/engage.py` `Engage.drop`, `content/engage/drops.json` | no (seeded per ship/day) | no |
| Cliffhanger card ("Tonight" / "Last night" + "This morning") | `web/engage.js` `hookBlock`, `tools/lve.py` `res` map | no (reads fired days) | no |
| Timed job | `Engage.job`, `content/engage/jobs.json`, `lv/clock.py` | no | no |
| Collections: patches, artifacts, crew file, story % | `web/engage.js`, `content/engage/collections.json` | no (derived) | no |
| Gifts and asks | record kind `GIFT=5`, op `O_GIFT`, `Engine._gift` | yes, signed 13-byte record | yes (small bond/morale) |
| Watch duty (streak with cover days, badges) | `engage.streak` | no (derived from the log) | no |
| Needs you (tiny visits) | `engage.waiting`, `Local` seen keys | no | no |
| Read again (end screen) | `app.html` `reread()` from text.json `"reread"` | no | no |
| LED notifier | `lv/led.py` | no | no |

## Features

* **Daily drop.** One sealed item per ship per flight day, picked from `drops.json` by tier
  (deterministic `day_seed(vk, day, S_DROP+ship)`, round-robin within a tier, a rarer
  tier guaranteed within 14 days). It never expires and opening it is ship-local
  (`Local.opened`, a bitmap).
* **Cliffhangers.** Content-voice's `h:1` hook cards fire at night and their resolver
  the next day. Home shows a rust-labelled **Tonight** card on the day a hook lands; the
  next day it shows **Last night** with the hook and **This morning** with its paired
  resolution (`engage.json` `res`, built by `lve.py` from the compiled pack's `C_FIRED`
  conds; all 10 hooks pair). If the resolver hasn't come in yet: a neutral "no word yet".
* **Timed job.** One job a day per ship, outcome fixed by the seed (`S_JOB`). Time only
  gates *when* the result is shown: the board learns the phone's clock from request
  headers and shows "about HH:MM" until then, "Done" after.
* **Collections.** Mission patches (milestones, drawn as plain line SVG; a neutral "how to earn it" line until earned), artifacts
  (found drops), the crew file (met / shared a line / traded with each crewmate) and
  story % (distinct non-ending cards seen / all non-ending cards).
* **Gifts and asks.** One give and one ask per flight day (the board enforces it); an ask
  can be answered by anyone until it lapses after 3 days. Gives and answers are records
  like votes, so every ship applies them identically: bond +2 (answer +4), target morale
  +2, one log line. Asks are private (no line). Nothing to a crewmate who is home.
* **Watch duty.** Any authored record on a flight day counts. Two missed days per flight
  week are covered automatically ("Phill covered", dashed box). Today never breaks it. When
  a run ends the screen just says a new watch starts with the next tap. Badges at 3, 7, 14,
  21, 30 and 42.
* **Needs you.** Home lists only what is waiting for *you*: today's drop, today's job,
  asks addressed to you, cargo in, open votes/dilemmas. New items since the last visit get
  a rust NEW. Fetching `/api/state` counts as a visit.
* **Read again.** After the ending, a list of flight days (no explanation) on which this
  ship's log shows a card listed in text.json `"reread"`; each row opens the log at that
  day.
* **LED notifier.** See below.

## Integration contract (firmware main loop)

`board/lvship.py` is the first main loop: BLE sync (README, "Ship-to-ship sync"), the
story, gifts in and out, the LED notifier (off unless `led_notify` is true in
`/data/ship.json`) and a small status server. The phone game server is still to come; it
follows this contract.

* Every phone request sends `X-Phone-Time` (epoch ms) and `X-Phone-TZ` (minutes east of
  UTC). Feed them to `Clock.learn_headers(get)`; out-of-range values are ignored, changes
  under 2 minutes are not applied (no jitter).
* `GET /api/state` adds `eng` = `Engage.view(...)`; `GET /engage.json` serves
  `build/engage.json` (3.0 KB gzipped, phone-side words; Pico keeps only
  `build/engage.bin`, 53 B).
* `POST /api/open {day}` opens a drop (today or earlier, own ship).
  `POST /api/gift {item,to,mode}` authors a `GIFT` record (mode 0 give, 1 ask, 2 answer;
  answers only to an open ask; 1 give + 1 ask a day).
* `Local` (opened drops, seen keys) persists to one small file per ship (`LVL1`, ~70 B);
  write it on visit/open, not every tick.
* LED: `Notifier(clock, enabled=ship_cfg.get("led_notify", False))`; set
  `waiting = bool(engage.waiting(...) unseen)` after each sync; call `poll(radio_busy)` in
  the loop's idle slot and sleep at most the ms it returns.

## LED risk notes

The Pico W's only LED is the user LED on the CYW43 radio chip's `WL_GPIO0`;
`Pin("LED")` toggles it with a command over the radio's SPI bus (no PWM; no separate
power LED). So: off by default (`led_notify` in `data/ship.json`, set from the updater's
section 4; the pin object isn't even created when off); 110 ms blink every 4.5 s; dark
22:00-07:00 phone-local and whenever the time is unknown; 4 lit minutes a day budget
(268 pin writes per 10 minutes in the test); never from BLE IRQs or scan callbacks; waits
while `radio_busy`. Searched `game/`, `newgame/`, `bench/` and `firmware/`: nothing else
drives the LED or creates `Pin("LED")`. If the coex bench shows any BLE/AP hiccup with
the notifier on, the fallback is to blink only between scan windows.

## Memory and size

MicroPython 1.29 unix, 32-bit (`build-m32`, closest to RP2040), eight ships, 274-record
reference season: story replay (`tests/mp_check.py`) peak 52.0 KB; story + engagement
(`tests/mp_engage.py`) peak 58.7 KB. 64-bit `build-standard`: 71.1 KB and 86.9 KB.
The page is 64 KB raw, 20.6 KB gzipped (15.7% of the 128 KB budget) with the epilogue screen.

**Heap fragmentation and the 64-bit OOM (core):** merging a long sync's worth of records
back to back could raise `MemoryError` on a dict resize with most of the heap free.
`ChoiceLog.merge` (lv/chlog.py) calls `gc.collect()` every 32 new records on MicroPython,
which fixed the 32-bit port, but `tests/mp_engage.py` still failed on the 64-bit port at
160 KB (one log-wide dict needing a ~3.5 KB contiguous block; it passed only from 192 KB).
The log is now sharded (one table per 8 authored days, from content-voice) and packed
(each shard's records sit back to back in one bytearray, the table maps key to offset), so
no table grows with the season and a record costs 13 bytes instead of its own heap object.
`mp_engage` now passes on 64-bit from 144 KB (run at 160 KB) and on 32-bit from 96 KB;
`tests/mp_merge.py nogc` no longer fails either, and the collection stays as a margin.
Heaps from .py include compiling `engine.py`; from .mpy (mpy-cross 1.29) the story check
runs in 80 KB (32-bit). Not yet confirmed on hardware.

## Content safety

Engagement text can show on any flight day, so it stays clear of the story:
`tools/lve.py` fails the build on any drop, job, gift, patch, artifact or crew-file line
that matches `content/engage/reserved.json` (maintainers only: it names the story's
threads, like STORY_BIBLE.md) or lvc's slow-burn vocabulary. Patches show a neutral
`lock` line until earned; their evocative line appears only after.

## Tests

`tests/run.sh` (with `MICROPYTHON=...`) runs lvc/lve, the unit and sim tests, the 8-ship
x 4-delivery-order determinism check, `tests/test_engage.py` (38 tests: merge collection, eight crew (Marco's gifts, drops, crew-file line, local file), content safety, drops, jobs,
streak/cover days, gifts limits, waiting/seen, clock, LED quiet hours/budget/disabled,
inactive season), render parity, page size, sign-in, the BLE sync tests
(`tests/test_sync.py`, `tests/mp_sync.py`, `tests/mp_sync_heap.py`) and the MicroPython checks.
`web/shots_engage.sh` writes the 390x844 screenshots.

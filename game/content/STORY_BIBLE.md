# The Long Voyage: story bible

**SPOILERS.** This file is for writers, not players. Don't quote it in reports,
PRs, commit messages or chat. Phill plays this game.

The house rules live in STYLE.md (voice, setting, the hard rule, skill flavor,
cliffhangers, content mix). This file covers what STYLE.md doesn't: the arc, the
motifs, what gets planted and where it pays off.

## The bar

- **Specific and sensory.** Name the thing: the Sharpie, the 11 seconds, the
  thumbnail, the water tanks. Never write "the vastness of space".
- **Economical.** One image per card, and the last sentence turns.
- **Equal dread and wonder.** A wonder card should carry a little cold, and a
  dread card should carry a little light.
- **The uncanny stays grounded and is never explained away cheaply.** Each
  answer is real physics or real hardware. It should make the thing stranger or
  sadder, not smaller.
- **People under pressure who are competent and kind.** Nobody panics for
  laughs. Nobody is the joke. The humor is how competent people breathe.
- **Motifs that come back changed.** Every recurring image means something
  different at the end than it did at the start.

## Shape of the voyage (flight days 1–42)

One flight day in the log stands for about five days of real flight (STYLE.md).

1. **Leaving (days 1–10).** Days 1–5 are in Earth orbit (a month-long tanker
   campaign, checkouts): Earth fills the window and calls home are live. The
   departure burn is day 6 (`l_departure`); the transfer-window routine starts
   day 7 (`l_transfer`). Plant everything here.
2. **The middle dark (days 11–24).** Earth becomes a dot, calls become letters,
   the carrier arrives (day 15) and gets an ordinary explanation (day 22).
3. **The approach (days 25–36).** Mars becomes a disc. The flash, the key, the
   ground answer; the orbiter theory stops working. The dust storm forces the
   arrival vote (`dust_worse` opens `dec_arrival`, about 2 seasons in 3).
4. **Arrival (days 37–42).** One mystery beat a day: checked (37), listen (38),
   count (39), reveal (40); day 41 the window (`a_window_*`, plus `a_log` when
   answered) and the descent call (`a_descent_*`), plus `a_recall_shared` and
   the last-night beat (`a_last_night` / orbit twin `a_last_night_o`); day 42
   prints the pre-entry beats first (`a_list`, `a_song`, `a_recall_*`), then the
   entry scene (`e_entry_*`, kept at the end of 55_voyage so it sorts last), then
   the ending. Thread beats (`c_*`, cat human) keep days 34–42 at two or more
   story cards a day (tested over 300 seasons).
   `test_climax_is_clear` and the 300-season test enforce it.

## The ramp (slow burn)

| Phase | Mystery content |
|---|---|
| 1 (days 1–10) | No mystery cards. Three phase-1 core clues hide in ordinary life: `l_reboot` (day 3, the screen counts eleven and logs out again), `l_manifest` (days 5–7, a shopping list ending on the socks; Cargo 2 is one of two written-off surface landers, beside an old science lander "silent since winter"). Phase 2 adds `l_dock_hello` (days 11–12, a transfer-hatch code goes stale relayed via the ground and opens first time ship to ship; filed as a page-two correction, with its own short tick). |
| 2 (days 11–24) | The carrier (`m_carrier`, due days 15–19) on the spare dish trained on Mars, called an alias, then retracted (`m_alias`, days 18–19: same millisecond on two ships, drifting against the fleet clock, opens `dec_signal`). The ripple (`m_ripple`, due every season). The crew's theory (`m_theory`, days 21–23): a written-off relay whose catalogued spin and beam width were both fitted to RF flashes heard after it failed. The 37-minute dropout (`m_dropout`, days 24–27, after the theory, so it reads as confirmation). |
| 3 (days 25–36) | The theory confirmed (`m_theory_confirm`, the decoy holds). The reply (`signal_reply` / `signal_echo`, days 25–27: the half frame, sets mark `t_frame`). The uncanny hooks (ghost and voice from day 25; `h_dark` days 26–29, only after `t_frame`, so the whole frame never precedes the half frame; `r_dark` 31–34). Tested in `test_fair_play_and_endings_over_300_seasons`. The clock (`h_band` / `r_band` days 30–35, or `c2_cold` 36–37): the knock is getting slower to wake. The flash (30), the second sighting and its vote (32), the key (34), the ground answer (35), the overlay (36). |
| 4 (days 37–42) | Checked (the ground hails), listen, count, the reveal (40), the window (41), the entry scene and endings (42). |

Measured (lvc ramp line): mystery cards by first day 0 / 6 / 15 / 6. Per season
(metrics, 300 seasons): 0.0 / 6.0 / 9.4 / 4.0 mystery cards fired by phase.
The WHAT (it's on the ground) is not inferable before about day 28: the
dropout lands after the theory, and the ground answer comes on day 35. The WHY
(late answers are discarded) is fair from day 11 (`l_dock_hello`) but is
meant to stay under 40% for a sharp reader until about day 33: the plant reads
as paperwork, and the divert / no-ack detail waits for `m_checked` (37).

## The twist, in layers

**Outer layer (what the crew believes from day 22):** something out there is
boot-looping. The decoy is a written-off relay orbiter in a one-sol orbit,
resetting forever; its 37-minute daily drift and the dropout fit the
evidence (`m_theory`, `m_dropout`, `m_theory_confirm`).

**Truth (day 40):** it's on the ground. Cargo 2 came down about thirty
kilometres long, tilted behind a crater rim, one solar wing half open, its dish
aimed at empty sky. Its flight computer reboots every eleven seconds; each boot
keys the beacon once and blinks the landing lights once (the self-test).

**Why it never stopped (hindsight):** the grey relay's thruster stuck open on
the burn to cover Cargo 2's landing pass, so Cargo 2 landed with no relay
overhead. Its X-band amplifier tripped OVERTEMP on the last packet and the dish
jammed against its stop. A watchdog restarts the flight computer every ~11 s.
Each boot, the boot ROM keys one link request (a "hello") on the old common
channel, signed with an old program key the fleet still trusts. The sequence
counter and the lost-link escalation timers live in RAM, so every boot sends
sequence number 1 with a fresh challenge, and no timer ever runs long enough to
escalate. The landing interlock then waits eleven seconds for a signed
answer to that challenge (the pad-test timeout, never changed for flight)
before resetting, with no back-off. The challenge lives in RAM, so it is new
every boot. Earth hailed it for
six weeks on the normal uplink (it heard every one on its low-gain antenna), but
Earth was always minutes away, so every reply answered a challenge that no
longer existed: the event recorder logged each `HELLO RX · REPLAY · DISCARD`.
Its own replies only ever went out on the old band.

**The 10.96 s coincidence, resolved:** in the weeks after the landing, Earth's
big dishes did hear flashes on the old band, every 10.96 s, and attributed them
to the tumbling relay. That is where the catalogue's "spin" for the relay comes
from (`m_theory`: "fitted to RF flashes from short ground passes, weeks
after it failed"), and why its beam width × spin gives exactly the flash duty cycle:
the catalogue was fitted to Cargo 2's flashes, so it matches by construction.
`a_report` closes it: the dead relay was the only orbiter on that channel.
Why the crash site was catalogued kilometres off: "the last fix before the
divert" (told in `m_checked`: "its last tone came mid-descent; at the end of that
track the search found a burn scar, booked as the impact. Six weeks of hails,
unanswered." The scar is the plume mark from the divert hover; `l_manifest` only lists
Cargo 2's drill spares, which `end_friend` / `end_long_orbit` / `end_close` pay off).
Why the search missed it: it found the hover scar at the end of the predicted track and booked it as the impact.
Why the fleet never had the same fault: every ship dumped its own fault table
(the last patch gave the cargo ships a divert branch, and only Cargo 2 ever
diverted, which is why Cargo 3 and Cargo 4 landed and work; `a_report`). Why the light
blinks: a low-duty pad strobe with each knock, the pad crew's "awake" sign
(`m_reveal`); after the answer the strobe stops and one status lamp stays lit
(`a_window_hail`). The floodlights only come on for a landing (`end_lights`) or
the rover (`end_friend`), which fits the battery rationing (`r_band`) and the cold
endings. Why no Doppler fix: the
flashes were too faint in short ground passes (`m_theory`). Why no hardware
bypass or hard reset: the pad table sits ahead of both decoders, and the dish a
hard reset needs is jammed (`a_log`, `a_window_quiet`). Why the old
key: first batch, the relay, the science lander, the early cargo, all dead or
crashed (`m_key`, day 34, every season; `r_dark` resolves `h_dark` on the next page with the hang only, no clue). Why no other orbiter
heard it: the relay was the only listener on that band. Why the relay was gone
at landing: its thruster stuck open a month before, and the landing went ahead
on the autonomous plan. Why it flew with pad-test settings: in cruise Earth talked to it on a session
set up on the pad; a last patch before landing restored the pad-test fault
table (the update thread pays off here), so on losing the link it fell back to
the short pad handshake. Why the ground never sent a bypass: see the hard-reset line above. The weather orbiter was written off before
landing; the night frames come from an old survey orbiter (`m_flash1`), and the
backup-site maps predate the cargo landings (`dec_name`). `c_theory`'s "Same keeper?" is answered by those lines.

**The window (day 41, fleet time):** Cargo 2 boots on a fixed 10.96 s tick (a
pad-test value; the fresh-question handshake is planted by the transfer hatches,
`l_dock_hello`, and named in `a_report`). Each cycle is
wake, pad-strobe flare with the knock, then dark while it listens until the next
tick (`m_reveal`: "nine, ten, eleven, flare");
the window is boot to reset, and the challenge and failure counter live in RAM.
The fleet is about 5.4 light-seconds out: knock at 04:10:07, heard about 5.3 s
later, answered at once; the answer lands a breath before the next tick, under
the ground's one condition (the handshake and nothing else). By the next
orbiter night pass the strobe has stopped; one status lamp burns steady. `HELLO RX · OK`. In the
log-it branch (`a_window_quiet`): it listens until its next tick; the fleet's
answer would take about ten seconds; the ground holds (no standing answer, a
review board that won't sit before landing, and a suit beside it).
**Blind hellos:** after the vote the fleet sends standard hellos blind; the
first whole frame decodes later (`m_key`/`r_dark`). Every hello is signed with
the old program key (`dec_signal`, `a_log`: "every one signed, every one late").

**Why nobody caught it (each gap has an in-world reason):**

| Who | What they saw | Why it didn't add up |
|---|---|---|
| Earth (comms) | Six weeks of ground hails, no acknowledgement | Every answer arrived minutes late and was discarded; Cargo 2's replies went out only on the old band, which Earth stopped listening to; X-band OVERTEMP, dish jammed (`m_checked`, `a_report`) |
| Earth (old band) | Flashes every 10.96 s in the first weeks | Attributed to the tumbling relay, written into its catalogue entry as a spin rate (`m_theory`, `a_report`) |
| Earth (security) | Signed link requests, sequence number 1, an old program key, no spacecraft ID | "Old key, first batch: the relay, the science lander, the early cargo. All dead or crashed." A parser guard goes up (answers keep going out); the first whole frame had hung the comms computer until a watchdog cleared it (`m_key`, `r_dark`) |
| Orbiter imaging | One coarse afternoon frame: a smudge and a streak | Backup-site maps predate the cargo landings (`dec_name`); from straight above a standing Starship is two pixels and a shadow; day 40 is the first sharp pass since (`m_reveal`) |
| The fleet, first look | A carrier on the dish, too faint to lock | Decoy 1: an alias of something aboard (`m_carrier`), killed when it lands on two ships' unsynchronised machinery in the same millisecond (`m_alias`) |
| The fleet, middle | 37-minute drift, out of view half the day | Decoy 2: the spinning relay "lighthouse" (`m_theory`, `m_theory_confirm`) |

**Control clues (the fair test):** `m_alias` shows the bursts are external
(simultaneous on two ships, drifting on its own crystal); `m_theory_confirm`
says the relay's orbit data is two years stale and no orbit it could have explains a carrier that sleeps half the day and wakes 37 minutes later each time; `c_theory` compares the swings (a relay
would drag the knocks by most of a tenth of a second each orbit, ±68 ms; these
swing by a hundredth once a day, ±11 ms: the size of Mars, turning);
`r_band` is no longer a clue (it carries the clock).

**Plants for the why:** the galley chime and counting to eleven, and the
screen that logs out again (`l_reboot`); the docking computer that discards a
the transfer-hatch code that goes stale relayed via the ground and opens
ship to ship (`l_dock_hello`);
the eleven-second gap and the shrinking round trip side by side on a
whiteboard (`m_count`);
the galley screen that waits for the ground's hello (`l_handshake`), the
comm-delay cards (`comm_delay`, `comm_delay2`, `h_silence`), "the interlock
won't move until they agree" (`dil_interlock`), the system text "One tap is
enough". The reveal has a crewmate counting to eleven, humming the chime.

**The vote that matters:** `dec_signal` (days 18–19, after `m_alias`).
*Answer every burst* sets a standing reply, the standard handshake signed with the old program key (costs:
comms-computer time, letters wait); then `a_window_hail` (day 41) lands the
answer in time, `a_log` plays the event recorder (×31,000 Earth hellos, then
×410,000 late fleet answers, then `HELLO RX · OK`), and the light stops
blinking. *Log it* means `a_window_quiet`: "The window after each knock is
eleven." Mission
Control asks the fleet to hold (no one knows what a two-year-old fault tree does
with its first good handshake), and the recorder comes down in person in every
unanswered ending (`end_through`, `end_patience`, `end_close`). The `dec_flash` vote (look / leave) changes who
learns it's on the ground and how (`flash_answer` vs `flash_answer_ground`,
`m_checked` vs `m_checked_g`); leaving it buys letters on time.

## Motifs

| Motif | Planted | Turns | Pays off |
|---|---|---|---|
| **The thumb** | Early watch: Earth spills out around a thumb | Middle watch: a thumbnail covers Earth | Day 41: Mars spills out around it again, and a light keeps time |
| **Eleven** | The galley chime; the fleet counts to eleven | The carrier's 10.96 s; the interlock | A crewmate counts to eleven, humming the chime |
| **The Sharpie hand** | The ration stash ("you'll thank me", a little ship, fingers crossed) | A spare not on the manifest; `sharpie2` | The crate coda in every ending |
| **What earlier missions left** | The manifest: Cargo 1/3/4 and one line for Cargo 2 | The relay decoy, the cover plate | Cargo 2, behind the crater rim |
| **The delay** | A live call, laughter landing in real time | A minute, then eight, then ten | Earth's answers always came too late |
| **The garden** | Seeds in the first week | Four pods fail | A shoot on the approach, unless the water was rationed |
| **The shelter between the water tanks** | Flare drills | The dose thread | Patting the tanks goodnight on the last night |

## Fair-play clues (surface → truth)

**Core clues** carry `clue core [GROUP]` (lvc). text.json `core` is a list of
groups; `sim/season.py --seasons 300` and the 300-season test fail if any group
has no member fired before the reveal day. Measured: 300/300 seasons, 9 groups.

| # | Card | Phase | Core | Surface | Truth |
|---|---|---|---|---|---|
| 1 | `l_reboot` | 1 | yes | A galley update, an in-joke about the chime | A boot is eleven seconds |
| 1b | `l_dock_hello` (11–12) | 2 | yes | A hatch-code procedure gets a page-two correction | Late answers are discarded as stale |
| 2 | `l_manifest` | 1 | yes | A shopping list: cargo ships, then write-offs (drill rig, grey relay, an orbiter, an old science lander, Cargo 2, socks) | Cargo 2, one of two surface candidates |
| 3 | System text `res_open` | all | – | UI copy | One tap is enough |
| 4 | `m_carrier` | 2 | yes | An old probe's beacon on the old channel | Cargo 2, every 10.96 s |
| 5 | `m_ripple` | 2 | – | A coolant-pump control loop hunting | The same rhythm in the noise floor |
| 6 | `m_dropout` | 2 | yes | Gone 37 minutes later each day: a one-sol orbit | Mars's own day: it turns with the ground |
| 7 | `m_theory_confirm` | 3 | – | The decoy confirmed | The decoy |
| 8 | `m_count` (39) | 4 | – | Lightning and thunder | The 11 s gap against the shrinking round trip |
| 9 | `m_flash1` | 3 | yes | A pixel on the night side | The floodlights at power-up |
| 10 | key: `m_key` / `r_dark` | 3 | yes | "Old key, first batch … All dead or crashed." | An old program key: it's one of ours |
| 11 | ground: `flash_answer` / `flash_answer_ground` | 3 | yes | It isn't in orbit | The decoy breaks |
| 12 | `m_overlay` | 3 | yes | Carrier and flash share a clock | The same machine |

Misdirections: `m_carrier` ("an alias, something of ours"; retracted by
`m_alias`, not a clue), `m_theory` / `m_theory_confirm` (the relay), `w_phosphene`
(cosmic-ray pixels), `r_ghost` (a cover plate shed at
departure, still flying with them), `m_key` / `r_dark` ("All dead or crashed."),
`signal_reply` (cut off before the sender field; it no longer claims a timing
change, so every branch agrees the averaged beat never moves).

## The reveal itself

`m_reveal` (`reveal`, day 40) is cast to the theory owner (`ow_theory`);
`m_reveal_any` is the fallback and never fires in 300 seasons. Understated: the
first sharp pass since before the cargo ships flew, Cargo 2 named once, dish
jammed against its stop, a pad strobe at each knock, the galley chime
fitting the gap. `a_report` (day 40) carries the sting and the root cause: the
relay was the only ear on that band; crash site from the last nav fix,
pre-divert; six weeks of hails, no ack; a carrier too faint for Doppler, called
relay tumble. `a_report` now has a speaker ({A} reads the fleet the only
paragraph that matters) and no page count.

## Threads (seven, one owner each per voyage)

Owners are bound with `who` on the opener and kept distinct with `!is`, so all
seven astronauts carry exactly one thread and every one gets an epilogue line.

| Thread | Opener (day) | Payoffs |
|---|---|---|
| list | `p_live_call` (1) | `p_list_letter`, `g_news` (27), `c_list` (35), `a_list` (42) |
| song | `p_music` (2) | `p_song_ask` (21), `c_song` (36), `m_listen` (38), `a_song` (42) |
| garden | `p_garden_plant` (4) | `p_garden_fail` (18), `p_garden_sprout` + `c_garden` (37) or `p_garden_none` (37) |
| letter | `l_letter` → `dil_letter` (8) | `letter_open` / `letter_worn`, `c_letter` (34), `a_letter` (40) |
| dose | `l_dose` → `dil_dose` (9) | `dose_swap` / `dose_ok`, `c_dose` (34), `a_last_night` (41) |
| hail | `m_carrier` (15) → `m_alias` → `dec_signal` (18) | `signal_reply`/`signal_echo` (25–27), `m_overlay` (36), `c_hail` (39), `a_window_*` + `a_log` (41) |
| theory | `m_theory` (22) | `m_theory_confirm` (25), `c_theory` (38), `m_reveal` (40), `a_recall_marker` (42) |

Each owner has one spoken line and one wrong-then-recover moment, usually in
the `c_*` beat (days 34–39, cat human so the one-mystery-a-day rule holds):
the hail owner's "Not us. Ignore my last.", the lost-then-found letter, the
tank argued for then pumped, the missing name added, the fifth bar played
wrong, the seedling put in the locker then taken back out, the lighthouse
redrawn. The packer has a setup (`p_packer_note`, day 16–17) before `g_packer` (day 28).

**Lasting cost:** the 02:00 thruster hook (`h_thruster` → `r_thruster`) leaves
the valve isolated: propellant, `valve_later` (24–33), and on day 39
`a_recall_valve`, a last simulator run one thruster short (skipped when the same
astronaut has the entry scene). Every unanswered ending keeps a cost past landing:
`end_through` loses a ship (a leg folds on the slope; it will not fly home),
`end_patience` finds Cargo 2 dead the night before landing (no OK), and
`end_close` hears one OK before its battery gives out. Their last lines change
accordingly ("All seven. Found the eighth."). A mid-voyage cost that lasts:
`r_strike` clears the struck ship for entry two degrees shallower, a longer,
hotter ride, "in every brief from now on".

**The clock (days 30–37):** `h_band` (days 30–34) has the knock miss once, the
first miss in weeks; `r_band` lays the gap against the night-side temperature
maps: six knocks late and still on the beat; a battery heater that skips
knocks rather than wake short of power. "It is getting harder to wake." The
tick never moves, so every return is on the beat (`c_hail`: "Every gap
explained"). Seasons without it get `c2_cold`
(36–37). Both are cat grim, not mystery, so days 35–40 keep one mystery card a
day.

**The climax on the page (day 42):** `idle_mentor` binds `abort_who` (the one
drilled on taking the landing by hand). `a_descent_hold` (41, answered) / `a_descent_hold_q` (41, unanswered: "Cargo 2's
knock for bearing") opens the formation (two minutes between ships) and has
them fly the take-manual "from memory"; then one entry scene per branch, cast to them,
printed after the other day-42 beats: `e_entry_hold`
(answered: Cargo 2's ping holds the bearing; `e_entry_hold_q` unanswered) (blackout, brown cameras, a gust, the take-manual called at a hundred metres
and the ship put down on the flat), `e_entry_wait`
(aerocapture, eleven seconds late, a manual corridor correction ready),
`e_entry_clear` (an engine lights a half second late; the engine-out call
catches). In the log-it branch `a_suit_plan` (42) has the hail owner, who argued
to answer, pack a handheld radio: "First one out goes to say hello." The endings then pick up the landing.

**Voices (per arc, not per person; see STYLE.md):** list: a talker, run-on,
thinks in lists ("no ums, no gaps, no saving the good bit for last"). Song:
taciturn, two-word lines ("Planet first.", "Not yet."). Garden: chats to the
plants, hopeful logs ("Wrong book," to the tray). Letter: formal, procedural
("Item located."), except the letter itself, which is never logged. Dose:
blunt, argues with numbers, grudging thanks ("Fair.", "Thanks for checking.").
Hail: timestamps, radio-terse ("No misses. Patient. Out."), then "Hi" out loud,
ten seconds early. Theory: visual, asks questions ("who keeps it?", "Same
keeper?"), draws in blue marker.

Costs carry forward: answering costs letters (morale), leaving the flash buys
them back, rationed water costs the garden, the wait branch costs fuel and food.
Endings cite the votes. The packer's loss is on the page (`g_packer`).

## Endings: hail × arrival (the core truth never changes)

Checked in deck order on day 42; first match wins. Titles come from `title`
(text.json `ti`). Every ending closes on the first crate ("You'll thank me.")
and the first message off the surface, to a loading bay at Starbase. Answered
endings close on the crate and "Landed. All eight." (the packer's count: seven
ships and Cargo 2). Unanswered endings pay a cost and close differently:
"All seven, one for good. Found the eighth." / "All seven. Found the eighth." /
"All seven. Found the eighth, in time." Endings may run to 640 characters (lint MAX_ENDING).

**Geometry:** day 41 is about five days (one log page) before atmospheric entry. Hold the plan
= retarget to the backup site, about three kilometres from Cargo 2, with radar
for height and Cargo 2's radio/transponder for place. The backup site is no
clearer than the prime zone, but it is flat, surveyed, and has a landmark that
answers. Aerocapture = a long orbit, then
the prime zone and a rover drive (Cargo 4's rover). Clear air = prime zone,
Cargo 2 thirty kilometres past it. Unanswered endings answer in person.

Cargo 2 has a job in every ending: floodlights as the place marker (`end_lights`),
answered from the crater rim by the one who argued to answer, one ship lost to a rim downdraft and an overloaded leg strut, no pilot blame (`end_through`); `end_lights` gets one extra granted command (lights), a manifest line read by pass and
a spare drill bit (`end_long_orbit`), found dead after the cold, answered by hand
(`end_patience`; from the long orbit the site rises minutes a day, low behind the crater rim), a rover drive with a real risk and every lamp flaring once as the rover's lights touch it (`end_friend`), the spare drill bit Cargo 3 needs for the water margin, and one OK before its battery dies (`end_close`). The
two storm endings open differently; the two orbit endings are scenes (week
three, week two), not summaries. The recorder paragraph is worded differently
in each.
Elapsed time since Cargo 2 landed: two years, everywhere.
Each needs ≥ 5% of 300 seasons (tested).

| # | Ending | Condition | Measured |
|---|---|---|---|
| 1 | *Lights On* (`end_lights`) | answered + held the plan | 21.0% (1000: 19.7%) |
| 2 | *Through the Dust* (`end_through`) | held the plan | 26.0% (22.5%) |
| 3 | *The Long Orbit* (`end_long_orbit`) | answered + aerocapture and wait | 14.7% (18.2%) |
| 4 | *Patience* (`end_patience`) | aerocapture and wait | 22.0% (18.9%) |
| 5 | *Old Friend* (`end_friend`) | answered, clear air | 8.3% (11.1%) |
| 6 | *Close Enough* (`end_close`) | clear air, not answered | 8.0% (9.6%) |

## Epilogue

`system.json` `epi.story` is a priority list of [card id, line]: thread payoffs
first, then openers, then a few fallbacks. lvc maps it to card indices.
`Renderer.epilogue` gives each astronaut the first line whose card they were
role A in; given the final state it fills any gap from the strongest trait
(`epi.axis`), the closest bond (`epi.bond`), or `epi.plain`, never repeating a
line, so the end screen always has seven (tested, including an empty log).
Measured: 7/7 from story lines alone in 300/300 seasons. Hand-off:
web/render.js has no epilogue yet; it should use the same fallback. `epi.coda` adds one line
for someone who isn't crew (name "Cargo 2"): the first card in its list that
fired, in any role, picks the line (`Renderer.coda`; tested present every
season). Hand-off: web/render.js should print it after the crew lines.

## Reading view

`Renderer.reader` (sim/out/reader.txt) folds each day's system echoes (actions,
crossings, notes) into one "around the fleet" line and prints the ending title
as a heading. Hand-off: web/render.js should do the same.

## Hand-off: text exposure on the phone (not built)

The phone fetches the whole `/text.json`, so every card, including the reveal
and endings, is readable on day 1, and card ids name the beats. Serving only
what has been unlocked would need, from lvc:
- a second output with text split per card (or per flight day), e.g.
  `build/text/<n>.json`, plus a small shared `sys`/`crew`/`actions` file;
- a served copy stripped of card ids and of the `core`, `reveal` and `reread`
  arrays (keep those for the sim and tests only);
- per-day keys (e.g. HMAC of the voyage key and the day) or a simple
  obfuscation so a fetched future chunk can't be read before its day; the Pico
  would hand out keys only for days reached, or serve chunks only for card
  indices already in the story log;
- epilogue/coda lines and ending titles moved into the day-42 chunk.

## The second read

Every clue card carries `clue`; text.json `reread` lists them. The end screen
can list the flight days they fired on, with no explanation.

## Characters

All seven are competent, kind, and tired in different ways. Each astronaut
belongs to a home ship; a ship may briefly hold 0 or 2 during a transfer window
(every fifth day from day 7) or an unscheduled rescue window. No crossing
out after day 32; from day 37 every visitor goes home, and nobody crosses on
days 40–42 (engine `TRANSFER_LAST_OUT`, `TRANSFER_HOME`; tested). Cards that
mention the transfer line say "the last/next transfer window". Skill flavor stays
subtle, in no more than about 1 card in 6.

## Cliffhangers

Mystery hooks (ghost, voice, dark) open days 25–33 and resolve by 34. The band
hook is now a grim clock (days 30–34, resolved 31–35).
Mundane hooks (silence, pressure, flood, strike, thruster) are capped at day 27
so days 25–33 favour the uncanny ones (ghost and dark weight 14). Resolvers give
no exact clock times for the hook night. Each resolves in grounded hardware
with a residue.

## Reserved words

engagement keeps `content/engage/reserved.json`: story words that engagement/UI
text must not use. That file lives on the engagement branch only, so this list is
the source to sync from. "Cargo 2" stays as the story's name.

Cargo 2, smudge, streak, shadow (of a ship), fingers crossed, self-test,
safe mode, safe-mode, pixel, night frame, fast sequence, spin, turns a minute,
between boots, old channel, retired channel, old common channel, aim for the
light, eleven / 11 seconds, 10.96, twelve now, pad-test, fault table, Sharpie, you'll thank me, written off, lost
on landing, landing lights, light-seconds, sol, Mars day, thirty-seven minutes,
37 minutes, interlock, transfer line, crater rim, solar wing, sequence number,
trusted key, program key, backup site, lighthouse, blue marker, galley chime,
chime, count to eleven, offline mode, replay, not ours, say again, keeps time,
watchdog, nonce, challenge (of a link request), ranging tone, hail box, event
recorder, REPLAY, DISCARD, HELLO RX, backup site, Landed. All eight., thruster
stuck open, against the stars, alias, Not us, afternoon orbit,
key rotation, auto-answer, fleet time, lost-link timer, boot ROM, OVERTEMP,
ground hails, sequence number 1, standard handshake, floodlights, dish jammed,
first sharp pass, two pixels, relay tumble, entry interface, plasma blackout,
The window after each knock is eleven, half a million, half the day, abort
call, keeper, Same keeper, Wrong lighthouse, eight and a half degrees, I'll be
counting, pad-test, lamp test, battery heater, slower to wake, still on time,
docking lead, last nav fix, weather mast, drill bit, All dead or crashed,
first batch, Old key, Item located, Wrong book, divert, page two, CODE STALE, Seven down, six to fly,
parser guard, blind hellos, first whole frame, Every gap explained, harder to
wake, take-manual, engine-out call, corridor correction, Found the eighth,
All seven, low-gain antenna, logo, bar, chime, eleven, First one out, say hello,
fault protection, a suit beside it, one Mars day, transponder.

## Round 8 notes

- Resolvers live in `cards/05_resolvers.lv`, which sorts first, so a resolver is
  the first due card of its day (only decision/dilemma closings come earlier;
  that order is the engine's and is not changed here).
- Endings: `end_through` / `e_entry_hold` are the same ship ("Seven down, six to
  fly."); `end_friend` sends the rover, drill spares first, no weather mast;
  `end_patience` powers the box before answering; `end_long_orbit` flies two
  passes. Epilogue and coda lines match their ending (system.json).
- A cost carries forward from mid-voyage: the rebuilt water processor tops out
  at 95% for good (`water_fail`).
- One respectful disagreement: a signed line of dissent in `dec_signal`.
- `c_theory`'s keeper is on the page as the Sharpie packer (`a_recall_marker`).
- `g_packer` moved to day 28 (fills the gap the half-frame retime left).

## Round 9 notes

- `m_carrier`: no one on Earth has *listened* to the old channel since the relay
  was written off (Earth did hear flashes in the first weeks; `m_theory`). A week
  of integration before the carrier shows.
- `gains_payoff` waits for the corridor burn (`trim_done`, set by both `dec_trim` options).
- The person who argued to answer (`ow_hail`) packs the drive bag in
  `a_descent_clear`, so the clear-air endings' driver is named the day before.
  In the unanswered branches `a_suit_plan` names the first suit out.
- Entry pilots get epilogue lines (`e_entry_hold_q`, `e_entry_hold`, `e_entry_wait`).
- Resolvers take a cost that stays: the reserve line (`r_pressure`), the last
  pump (`r_flood`), one thruster short (`r_thruster`).
- The ripple pays off in `m_count` (day 39).
- Wonder: `w_zodiac`, `w_sun_small`; `w_aurora`, `beat_watch`, `beat_early_watch`
  are now wonder; `dust_report` / `dust_worse` are mission.
- Fold lines in the sim reader are left out on odd days that already have two
  story lines (sim/render.py only; web/ untouched).
- Casting: `p_live_call` is even over 300 seasons (37–49 each). The take-manual
  trainee (`idle_mentor` B) leans to whoever is least featured mid-voyage, which
  is engine fairness at work; unchanged.

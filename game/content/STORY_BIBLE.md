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
| 1 (days 1–10) | No mystery cards. Three phase-1 core clues hide in ordinary life: `l_reboot` (day 3, the screen counts eleven and logs out again), `l_manifest` (days 5–7, a shopping list ending on the socks; Cargo 2 is one of two written-off surface landers, beside an old science lander "silent since winter"). Phase 2 adds `l_dock_hello` (day 12, a transfer-hatch code goes stale relayed via the ground and opens first time ship to ship; filed as a page-two correction, with its own short tick). |
| 2 (days 11–24) | The carrier (`m_carrier`, due days 15–19) on the spare dish trained on Mars, called an alias, then retracted (`m_alias`, days 20–21: same millisecond on two ships, drifting against the fleet clock, opens `dec_signal`). The ripple (`m_ripple`, day 14, every season). The crew's theory (`m_theory`, days 21–23): a written-off relay whose catalogued spin and beam width were both fitted to RF flashes heard after it failed. The 37-minute dropout (`m_dropout`, days 24–27, after the theory, so it reads as confirmation). |
| 3 (days 25–36) | The theory confirmed (`m_theory_confirm`, the decoy holds). The reply (`signal_reply` / `signal_echo`, days 25–27: the half frame, sets mark `t_frame`). The uncanny hooks (ghost and voice from day 25; `h_dark` days 26–29, only after `t_frame`, so the whole frame never precedes the half frame; `r_dark` / `r_dark_a` 27–32). Tested in `test_fair_play_and_endings_over_300_seasons`. The clock (`h_band` / `r_band` days 30–35, or `c2_cold` 36–37): the knock is getting slower to wake. The flash (30), the second sighting and its vote (32), the key (34), the ground answer (35), the overlay (36). |
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
divert". Since round 16 `m_checked` no longer mentions a scar (it only says
nothing on file near the pixel has power, and two weeks of hails on the old key
went unanswered); the "impact scar" is named once, in `a_report`, as Cargo 2's
aft skirt, shed uprange before the divert. `l_manifest` only lists
Cargo 2's drill spares, which `end_friend` / `end_long_orbit` / `end_close` pay off).
Why the search missed it: it found the shed aft skirt on the predicted track and booked it as the impact, and its three short passes read the knock as the relay's spin (`a_report`).
Why the fleet never had the same fault: every ship dumped its own fault table
(the last patch gave the cargo ships a divert branch, and only Cargo 2 ever
diverted, which is why Cargo 3 and Cargo 4 landed and work; `a_report`). Why the light
blinks: a low-duty pad strobe with each knock, the pad crew's "awake" sign
(`m_reveal`); after the answer the strobe stops and one status lamp stays lit
(`a_window_hail`). The floodlights only come on for a landing (`end_lights`) or
the rover (`end_friend`), which fits the battery rationing (`r_band`) and the cold
endings. Why no Doppler fix: the
flashes were too faint in short ground passes (`m_theory`). Why no hardware
bypass or hard reset: the replay check sits ahead of every command path, and the
dish a hard reset needs is jammed (bible only since round 10; the cards no longer
say it). Why no working orbiter answered: none carries the old channel and key;
only the dead relay did (`a_report`). Why Cargo 2 diverted: boulders on its pad;
the aft skirt it shed uprange is what the search booked as the impact (`a_report`). Why Earth never caught the half-sol outages: the catalogue fit used
three short passes (`m_theory`); the 37 minutes is decoded once, late, in
`c_theory` (day 38). Why the old
key: first batch, the relay, the early cargo, all dead or
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
review board that won't sit before landing, and a ruling: AFTER LANDING. LINE OF
SIGHT, INSIDE THE TICK; `end_through` answers from two hundred metres on the rim).
**Blind hellos:** after the vote (and the ground's clearance: hello only,
nothing that commands) the fleet sends standard hellos blind; a whole frame
decodes later (`m_key`/`r_dark`). Every hello is signed with
the old program key (`dec_signal`, `a_log`: "every one signed, every one late").

**Why nobody caught it (each gap has an in-world reason):**

| Who | What they saw | Why it didn't add up |
|---|---|---|
| Earth (comms) | Six weeks of ground hails, no acknowledgement | Earth never heard a challenge, so none of its 31,000 hails was signed to one (`a_log`: NO OPEN CHALLENGE); the fleet's later answers were late (REPLAY); Cargo 2's replies went out only on the old band, which Earth stopped listening to; X-band OVERTEMP, dish jammed (`m_checked`, `a_report`) |
| Earth (old band) | Flashes every 10.96 s in the first weeks | Attributed to the tumbling relay: three passes of under an hour on a spare antenna that measured power, not frequency, so no Doppler and no day-long drift; nothing else spoke that channel (`m_theory`) |
| Earth (commanding) | Two years of resets, never out of pad-test mode | The pad check-in masks the lost-link timer and the flag lives in non-volatile memory, so it outlives every reboot; only the relay spoke its channel or could send a hard reset (`a_report`) |
| Earth (security) | Signed link requests, sequence 5,750,112 (a boot counter kept in flash: one per knock, so ×10.96 s ≈ two years, dating the source to the cargo landings), an old program key, no spacecraft ID | "Old key. Retired with the first batch. Nothing on it still flies." (no list: round 11 widened the suspects) The first whole frame had hung the comms computer: a healthy thread kept its watchdog fed, the hourly health check rebooted it, and the backup string, fed the same frame, hung too (`m_key`, `r_dark`) |
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
whiteboard (`m_count`, cut in round 15; the shrinking round trip now lives in
`m_overlay` and `a_window_*`, and day 39 carries `c2_clock`, the cold clock);
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
| 1b | `l_dock_hello` (12) | 2 | yes | A hatch-code procedure gets a page-two correction | Late answers are discarded as stale |
| 2 | `l_manifest` | 1 | yes | A shopping list: cargo ships, then write-offs (drill rig, grey relay, last year's hopper, Cargo 2, socks) | Cargo 2, one of two surface candidates (the hopper is the decoy) |
| 3 | System text `res_open` | all | – | UI copy | One tap is enough |
| 4 | `m_carrier` | 2 | yes | An old probe's beacon on the old channel | Cargo 2, every 10.96 s |
| 5 | `m_ripple` | 2 | – | A coolant-pump control loop hunting | The same rhythm in the noise floor |
| 6 | `m_dropout` | 2 | yes | Gone 37 minutes later each day: a one-sol orbit | Mars's own day: it turns with the ground |
| 7 | `m_theory_confirm` | 3 | – | The decoy confirmed | The decoy |
| 8 | `c2_clock` (39) | 4 | – | The beat is running out | The cold gap and the weaker knock: Cargo 2 is losing its battery, so arrival day matters |
| 9 | `m_flash1` | 3 | yes | A pixel on the night side | The floodlights at power-up |
| 10 | key: `m_key` / `r_dark` | 3 | yes | "Old key. … only the relay kept it." | An old program key: it's one of ours |
| 11 | ground: `flash_answer` / `flash_answer_ground` | 3 | yes | The pixel never moves against the rocks | The decoy breaks (no longer said aloud) |
| 12 | `m_overlay` | 3 | yes | Carrier and flash share a clock | The same machine |

Misdirections: `m_carrier` ("an alias, something of ours"; retracted by
`m_alias`, not a clue), `m_theory` / `m_theory_confirm` (the relay), `w_phosphene`
(cosmic-ray pixels), `r_ghost` (a cover plate shed at
departure, still flying with them), `m_key` / `r_dark` ("Nothing on it still flies."), last year's hopper
(`l_manifest` "tipped over, last heard sol 9"; `m_flash2`, the ground's first guess;
it flew on a newer key, so `m_key` on day 34 rules it out for a careful reader;
`m_checked` puts it 90 km south, still silent),
`signal_reply` (cut off partway; it no longer claims a timing
change, so every branch agrees the averaged beat never moves).

## The reveal itself

`m_reveal` (`reveal`, day 40) is cast to the theory owner (`ow_theory`);
the old fallbacks (`m_reveal_any`, `a_report_any`) were removed in round 10, because `m_theory` and `m_flash1` fire in every season, so the owners always exist (checked over 1,000 seasons). Understated: the
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
maps: six knocks late and still on the beat (the battery-heater explanation
is no longer said; it is left to the reader). "It is getting harder to wake." The
tick never moves, so every return is on the beat (`c_hail`: "Every gap
explained"). Seasons without it get `c2_cold`
(36–37). Both are cat grim, not mystery, so days 35–40 keep one mystery card a
day.

**The climax on the page (day 42):** `idle_mentor` binds `abort_who` (the one
drilled on taking the landing by hand). `a_descent_hold` (41, answered) / `a_descent_hold_q` (41, unanswered: "Cargo 2's
knock for bearing") opens the formation (two minutes between ships) and has
them fly the manual takeover "from memory"; then one entry scene per branch, cast to them,
printed after the other day-42 beats: `e_entry_hold`
(answered: Cargo 2's ping holds the bearing; `e_entry_hold_q` unanswered) (blackout, brown cameras, a gust, the manual takeover called at a hundred metres
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
(text.json `ti`). Every ending closes on the first message off the surface,
to a loading bay at Starbase, and since round 16 on the loading bay's reply
("From a loading bay, later: "Told them it sulks.""). The first crate ("You'll
thank me.") stays in `end_lights`; the Sharpie hand also returns on day 38
(`a_recall_shared`). The renderer prefixes every ending with `sys.end`, now
"From the log:" (was "Arrival day.", which clashed with endings set sols later).
Every answer is HELLO then HOLD on the next tick (the patch says ON HELLO: WAKE
ALL), and every power draw in an ending has a named source. Since
round 14 every ending pays a price, answered or not. Answered endings: *Lights
On* spends Cargo 2's floodlights ("All seven. The eighth kept the lights on."),
*The Long Orbit* loses the seed stock in Cargo 2's hold (the lamp stayed lit,
the heater didn't; "Landed. All seven. The eighth was waiting."), *Old Friend*
ruins the rover's pack (half range for the mission, a ground waiver for the
drive; "All eight.", the only ending that says it). Unanswered endings close "All seven, one
for good. Found the eighth." / "All seven. Found the eighth." / "All seven.
Found the eighth, in time." Endings may run to 640 characters (lint MAX_ENDING).

**Geometry:** day 41 is about four days before atmospheric entry (at an arrival v∞ of about 4.2 km/s that is about 1.45 million km, 4.8 s one-way, 9.7 s round trip, inside the 10.96 s tick; five days would be about 12 s and miss it). Hold the plan
= retarget to the backup site, about three kilometres from Cargo 2, with radar
for height, the last orbiter fix for place and Cargo 2's radio as a cross-check (round 16). The backup site is no
clearer than the prime zone, but it is flat, surveyed, and has a landmark that
answers. Aerocapture = a long orbit, then
the prime zone and a rover drive (Cargo 4's rover). Clear air = prime zone,
Cargo 2 thirty kilometres past it. Unanswered endings answer in person.

Cargo 2 has a job in every ending: floodlights as the place marker (`end_lights`),
answered from the crater rim by the one who argued to answer, one ship lost to a rim downdraft and an overloaded leg strut, no pilot blame (`end_through`); `end_lights` gets one extra granted command (lights), a manifest line read by pass, a
spare drill bit and the frozen seed stock (`end_long_orbit`; no tile line, since an ending can't bind the r_strike astronaut), found dead after the cold, answered by hand
(`end_patience`; from the long orbit the site rises minutes a day, low behind the crater rim), a rover drive past the point of return, judged by Cargo 2's knock on the rover radio (the lamp is below the horizon at 30 km), rescued by the leg charge port planted in `g_packer`'s forklift photo, paid for with the rover's pack (`end_friend`), the spare drill bit Cargo 3 needs for the water margin, and one OK before its battery dies (`end_close`). The
two storm endings open differently; the two orbit endings are scenes (week
three, week two), not summaries. The recorder paragraph is worded differently
in each.
Elapsed time since Cargo 2 landed: two years, everywhere.
Each needs ≥ 5% of 300 seasons (tested). The 300-season spread is mostly vote
noise (about ±2 points per ending); judge balance on 1000 seasons.

**Named roles (round 13).** Every ending carries `roles A B`: A is always the
hail owner (`is A ow_hail`, the one who first heard the carrier); B is the
gust pilot (`abort_who`, set by `e_entry_hold*`) in `end_lights` and
`end_through`, the one who argued to wait (`wait_who`, set by `dec_arrival`'s
wait option since round 15) in `end_long_orbit`, and the theory owner (`ow_theory`) in the three that turn on the
lighthouse. The engine picks the ending on flags first, then fills roles from
the ending's `is` tests only (no casting, so A and B may be the same person;
the texts read correctly either way). lvc rejects any other role test on an
ending, and any role test on the fallback.

| # | Ending | Condition | Measured |
|---|---|---|---|
| 1 | *Lights On* (`end_lights`) | answered + held the plan | 14.7% (1000: 16.0%) |
| 2 | *Through the Dust* (`end_through`) | held the plan | 17.3% (1000: 17.8%) |
| 3 | *The Long Orbit* (`end_long_orbit`) | answered + aerocapture and wait | 17.0% (1000: 17.2%) |
| 4 | *Patience* (`end_patience`) | aerocapture and wait | 16.3% (1000: 14.9%) |
| 5 | *Old Friend* (`end_friend`) | answered, clear air | 16.7% (1000: 16.3%) |
| 6 | *Close Enough* (`end_close`) | clear air, not answered | 18.0% (1000: 17.8%) |

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
belongs to a home ship; a ship may briefly hold 0 or 2 during a crossing window
(every fifth day from day 7) or an unscheduled rescue window. No crossing
out after day 32; from day 37 every visitor goes home, and nobody crosses on
days 40–42 (engine `TRANSFER_LAST_OUT`, `TRANSFER_HOME`; tested). Cards that
mention the transfer line say "the last/next crossing window". Skill flavor stays
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
ground hails, sequence number, standard handshake, floodlights, dish jammed,
first sharp pass, two pixels, relay tumble, entry interface, plasma blackout,
The window after each knock is eleven, half a million, half the day, abort
call, keeper, question mark, eight and a half degrees, I'll be
counting, pad-test, lamp test, battery heater, slower to wake, still on time,
docking lead, last nav fix, weather mast, drill bit, All dead or crashed,
first batch, Old key, Item located, Wrong book, divert, page two, CODE STALE, Seven down, six to fly,
parser guard, blind hellos, first whole frame, Every gap explained, harder to
wake, manual takeover, engine-out call, corridor correction, Found the eighth,
All seven, low-gain antenna, logo, bar, chime, eleven, First one out, say hello,
fault protection, line of sight, one Mars day, transponder, ON HELLO: WAKE ALL,
The eighth was waiting.

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
- Casting: `p_live_call` is even over 300 seasons (37–49 each). The manual takeover
  trainee (`idle_mentor` B) leans to whoever is least featured mid-voyage, which
  is engine fairness at work; unchanged.

## Round 10 notes

- **Reveal room.** Day 40 now carries only `m_reveal`, `a_report`, the crater
  recall (`a_recall_home` / `a_recall_plan`) and, sometimes, `a_recall_shared`.
  `a_letter` moved to day 39, `a_recall_wrist` to day 37, and `w_phobos` (now
  wonder) to days 37–39.
- **`a_report`** has a speaker, one idea per sentence, the orbiter answer, the
  divert cause, and "logged, thanked, thrown away".
- **Day 41 timing.** `a_window_quiet`: ten seconds there and back is *inside*
  the tick; nothing is cleared to answer, and the ground doesn't want fault
  protection waking mid-descent while the fleet steers by the knock (this is why
  a suit beside it after landing is acceptable). `a_window_hail`: "the handshake
  and nothing else, until the review board sits". "Four days out" everywhere.
- **Command authority.** The board sits before entry and clears one more
  command: lights (`end_lights`, sent by the one who answered) or the manifest
  dump (`end_long_orbit`). In `end_friend` nothing is commanded: the rover's
  radio on the old channel triggers the pad crew's arrival routine.
- **Light delay.** `comm_delay` is a minute each way (days 16–19); `photo_back`
  no longer names a delay; `h_flare` has the fleet's own X-ray monitor first.
- **Flight rules.** Solo loop changes now cost a non-conformance report
  (`dil_gains`, `gains_payoff`); the valve fix is an uplinked thruster-select
  table (`valve_later`); the key rides in a crypto slot (`a_suit_plan`).
- **Casting.** `l_reboot` (day 3–9, cast evenly) now sets `abort_who`, and
  `idle_mentor` requires `is B abort_who`, so the manual takeover trainee is even
  across the crew (37–48 each over 300 seasons).
- **Blank days.** `w_milky` (day 20) and `w_moon_pair` (day 22) are due wonder
  cards; blank story days on 20 and 22 drop to 0.
- **Fold lines** (sim reader only) appear on quiet days and every third day,
  and the pool is ten specific lines rather than stock phrases.
- Retired gestures: "stays a while", "doesn't explain", "It isn't two things",
  "harder to wake", "fits the knock exactly".
- `h_band` waits for `flash_seen` and ends on the dark pixel; `r_band` ends
  "Each cold night the gap is a knock or two longer."

## Round 11 notes

- **Difficulty.** Cut the over-explanations: `m_count` no longer recalls the
  0.09 Hz ripple (it now pays off in the epilogue, `m_ripple`: "blamed a
  pump"), `c_theory` keeps "thirty-seven minutes too long" and drops the
  sidereal-day solve, `r_band` drops the battery heater, `m_key` drops "the
  kind that goes stale" and the suspect list, `dec_signal` drops "anything we
  ever flew". Announcing lines removed: "isn't in orbit", "a byte before the
  field that says who sent it", "first contact". Day-11 (`l_dock_hello`) and
  day-16 (`m_ripple`) plants unchanged.
- **Live decoy.** `m_flash2` (day 32) ends on the ground's first guess, the old
  science lander, silent since its winter; `m_checked` (37) places it 400 km
  east, still silent, before naming the crash site.
- **Order.** `m_carrier` 15 → `m_theory` 17 (the grey relay, "a lighthouse
  with no keeper") → `m_alias` 19 (not aboard, probably dead) → `dec_signal`
  19–20, now a vote on answering a dead lighthouse, with the ground's clearance.
  `m_alias` still opens `dec_signal` (role preset needs an `ow_hail` opener).
- **Earth's answers.** "Six weeks" of hails (`m_checked`, `a_log`). `a_log`
  splits the counts: 31,000 Earth hails "NO OPEN CHALLENGE" (never signed to a
  question it heard) vs 410,000 fleet hellos "REPLAY" (late). `m_theory`: the
  relay's catalogue spin came from power-only passes under an hour (no
  Doppler, no day's drift). `a_report`: the pad check-in masks the lost-link
  timer, outlives a reboot, and only the relay spoke its channel. `g_packer`:
  "and the relay before that".
- **Flight rules.** Ground clearance for the hail (`dec_signal` open option,
  `sys.dec_open`: "the flight director will go with the fleet's call").
  Symmetric day-41 rule: an entry freeze, nothing new on the comms schedule
  inside a week of entry; the answered hello was cleared at the vote, the quiet
  branch has no link for a review board to review. Solo crew: one seat per
  ship so no single failure takes two people (`l_transfer`).
- **Numbers.** `m_alias` drift "about two seconds a day" (the closing rate).
  Earth delays: `signal_reply` six minutes (FD25 round trip 5.7), `comm_delay2`
  five light-minutes (now day 33 only), `a_list` eight minutes (FD42 8.2).
  `w_mars_disc` day 41: half-lit, dawn line down the middle. Entry: storm brown
  to 300 m, then plume brownout (`e_entry_hold*`, `end_lights`). `end_long_orbit`:
  hinge-line tile runs hot "on the way down". Close Enough's cost has a cause:
  Cargo 3's only drill bit snaps on the first sol; the bit is planted on day
  31 by a new due card, `a_drill_plan` ("Be gentle with it"), and the old
  single-bit line left `a_descent_clear`.
- **Continuity.** Fold line no longer quotes 93%. Portrait: days 2–5, Earth
  fills the frame; `photo_back` is "weeks ago now" and keeps six ships plus the
  edge of the seventh. `r_ghost`: a few metres a day, end over end. Epilogue
  `e_entry_hold_q`: "walked out on legs that held". `end_friend` light is
  "steady since the handshake". `h_dark` now never lands on the hail owner and
  explains the frame came over the fleet net from the listening dish; weight
  30 (≈55% of seasons; hooks are random, so every season can't be forced).
  `glint` is now a waste-water ice flake, distinct from `h_ghost`'s tracker
  scare and `r_ghost`'s cover plate.
- **Endings as scenes.** All six rewritten as scenes under 640 characters,
  first sentence short (the web uses it as the heading). Measured at 1000
  seasons: lights 19.8%, patience 17.5%, long orbit 16.8%, friend 15.4%,
  close 15.4%, through 15.1%.
- **Character.** `habit_beat` is commented out (all seven roster habits are
  placeholders, so it read the same for everyone); restore it when real habits
  arrive. Seven generic, castable objects carried aboard (`hb_watch`,
  `hb_pebble`, `hb_key`, `hb_card`, `hb_pick`, `hb_leaf`, `hb_stub`), weight 1,
  days 12–36: about six per season over four or five people. They are fiction
  about objects, not claims about the real crew.
- **Mystery leads.** `m_flash1` and `m_overlay` no longer go to the hail owner
  (`m_overlay` also avoids the flash and theory owners). Max mystery cards on
  one person per season: mean 6.65 → 5.37.
- **Tension tail.** `r_flare` leaves a "lifetime" dose column.
- **Polish.** "log/logs/logged" cut from about 38 to about 8 per season
  (mostly `sys.dec_open`); "It was a Tuesday" gone; `a_recall_marker` moved to
  day 41; humor flags (`storm_shelter2`, `l_long_table`, `galley_pump`,
  `dec_clock`) softened so nothing stings a crewmate.
- **Ending titles.** The phone/web never prints `ti`; `app.html` uses the
  ending's first sentence as the heading. But `/text.json` is fetched whole on
  day 1, so titles and endings are readable in devtools: see the text-exposure
  hand-off above (strip `ti` or move it to the day-42 chunk).

## Round 12 notes

- **Delay the who.** Second surface suspect: `l_manifest` lists last year's
  hopper ("tipped over, last heard sol 9") in place of the old science lander
  (and drops "an orbiter" for length; `dec_name` still says one was written
  off). `m_flash2` ends on the ground guessing the hopper. The hopper stays
  live until `m_key` (day 34: old key, first batch, two years) splits them.
  `m_checked` / `m_checked_g`: the hopper is 90 km south and silent; the
  nearest scar was "filed two years ago as impact debris" (no cargo number;
  "Cargo 2" is first named again in `m_reveal`). `c_theory` ends on a question
  mark under the keeper (no "Wrong lighthouse / Same keeper?"). `c_hail` drops
  "Patient."; `m_alias` ends "Not aboard, then", books the dish again;
  `m_theory` drops "a lighthouse with no keeper" (it sketches a lighthouse; the
  keeper arrives in `m_theory_confirm`). `signal_reply` / `signal_echo`: "a
  format the receiver has to look up" (was "no one flies now"). Day-11 plant and
  every why-clue unchanged.
- **Mechanism.** `a_report`: the last patch, tested on the pad, took the
  divert for a pad landing and waits for the pad crew; reboots don't clear it
  (the latch is post-touchdown). `m_theory`: the relay's thruster stuck open
  just before the cargo landings; the catalogue passes came after.
  `dec_signal`: the fleet carries the old key "as a relay fallback"; `sharpie2`
  now finds the key card under the tape roll, "Old manners, for old hardware"
  (fires in ~all seasons, but `dec_signal` stands alone). `a_log`: "HAIL RX ·
  WRONG CHALLENGE ×31,000" (Earth) and "HELLO RX · LATE · DISCARD ×41,000"
  (only the hellos that locked are counted; the rest were too faint to class).
  `a_window_quiet`: the ground drafted a reply the day the key decoded; it
  reached the board a day into entry week, and the board won't wake Cargo 2
  until every ship is down, in orbit or not (covers slot 4 and pre-staging).
  `a_window_hail`: handshake only (since round 16: the hello, then a HOLD on the next tick). `r_dark`:
  back "before the third hour was out" (two reboots), frame relayed from the
  listening dish, and the ground puts the old channel under review and
  filters it.
- **Realism.** `dec_trim` residual under a millimetre per second. `r_ghost`:
  a few metres a minute, slides past tonight; Starbase counts its cover plates.
  `r_strike`: entry a few tenths of a degree steeper (sharper peak, shorter
  soak); its "in every brief" plant is cut, and `end_long_orbit`'s hinge-line
  tile stays generic. `r_strike` B must be `cond ok` and not the injured EVA
  astronaut. `water_good`: thousandth hour, gated `since t_water >= 9`.
  `dil_interlock` override stalls at ten kilopascals on a slow leak.
  `dil_eva_cam` go waits for the ground's GO on the next pass. `storm_dose`:
  "close to fifty". `w_venus_shadow`: so faint you move the hand to see it.
  "take-manual" is now "manual takeover" everywhere.
- **Continuity.** `c_dose`: "because the flight surgeon once asked".
  `p_movie` names {B}. `l_transfer` moved to day 2 (premise up front: one seat a
  ship, close up every few days); `l_long_table` is now due on day 7.
  `m_listen`: "a few pages out". `a_list`: "sends them without a single pause".
  `w_phosphene`: "shuts both eyes". `dil_gains`: "a second signature line added
  for next time". `end_patience`: typo fixed, "the one who wanted to answer
  weeks ago", a battery choosing which knock to skip. `end_close`: the spare
  batteries went into the rover's heaters on the second night; flight mode
  wakes every survival heater before it reads the battery. `end_friend`: two in
  the cab. `end_lights` starts on the ground (`e_entry_hold` now stops at the
  manual-takeover call, so the ending no longer rewinds). `end_long_orbit`:
  the lamp blinks twice when the fleet passes over.
- **Epilogue.** `epi.story` now leads with the landing pilot's lines
  (`e_entry_hold_q` "kept the ship upright on a folded strut", `e_entry_hold`,
  `e_entry_wait`), then the window lines, then a new `e_entry_clear` ("kept the
  engine-out call behind their teeth"). `a_log` copies the Earth count into the
  notes ("reads twice" retired).
- **Habits.** Three remain, one per thread owner, so never two on one person:
  `hb_watch` (`ow_dose`, days 12–20), `hb_card` (`ow_list`, clipped in the
  flight-plan binder), `hb_leaf` (`ow_letter`, sleeve pocket, "files it as a
  status"). Cut: pebble, key, pick (clashed with the song), stub. No
  "nobody", tape, or "clipped above the bunk".
- **Tension.** New irreversible loss, `l_crystals` (grim event, days 20–28,
  weight 40, ~98% of seasons): a lab's protein crystals cook when a freezer fan
  seizes; no second batch. `h_dark` days 26–31, weight 90 (~76–80% of seasons;
  hooks stay random behind HOOK_GAP/HOOK_PCT). `r_dark` due 27–32. `h_band`
  weight 60 (~69%). `h_voice` can't move before day 25 (lint: early hooks stay
  grounded).
- **Sim reader.** `fold_pool` is 16 lines; the fold shows on quiet days and
  every third day, so a pool length coprime with 3 keeps the same line from
  recurring on days 6/21/36. `sys.dec_open`: "Both options are cleared; the
  flight director wants the fleet's call." `dust_report` weight 5 (endings
  stay even).

## Round 13 notes

- **Engine (own commit).** `O_END` now carries two crew slots; `render.py`,
  `web/render.js` and `web/app.html` fill `{A}`/`{B}` in the ending text and
  title. Hand-off: the web ending screen reads the two slots from the O.END
  entry. Digest unchanged for decks without ending roles; heap 72.6 KB.
- **Presence.** A card that puts {A} at their own ship now says so in its
  conditions (`when home A`, 24 cards), `p_birthday` / `beat_haircut` need
  {A} away and {B} home, `rescue_kit` needs B and A apart. New test: over 300
  seasons every A/B whose text implies home/away/together is checked against
  the ship state when the card fires (6,800+ checks, zero misses; `r_strike`
  exempt because its "ship" is the entry profile, not a location).
- **Logic.** `a_report`: the last patch files any touchdown on a surveyed site
  as a pad, and the backup site was surveyed; on a pad it obeys the pad crew
  (knock, listen one tick, knock again); Earth is sixteen minutes away, the
  tick is eleven seconds. `a_log`: five weeks of Earth's hails; the fleet's
  hellos ran about twenty ticks late at first, one at the last. `m_key`: the
  first batch was re-keyed after landing; only the relay kept the old key.
  `p_packer_note` plants "Ours won't arm till someone says hello."
  `r_dark` is now unanswered-only (channel off the fleet net, dish keeps
  recording); new `r_dark_a` for answered voyages (sandboxed on the dish).
  `dec_name` names the grey relay as the only sharp camera at Mars;
  `m_reveal` is the long lenses' first sharp pass in two years.
- **Harder who.** `l_manifest` / `m_flash2` / `m_checked*`: the hopper is
  "tipped, beacon intermittent" (not silent), so it stays a live suspect until
  `m_key`. `m_carrier` closes on "An alias, probably." `m_theory_confirm`
  drops the sleeping keeper; `c_theory` is "Under the lighthouse". `g_packer`
  no longer counts ships out loud.
- **Clock.** `c2_cold` frames the cold gaps as converging on a date a few
  nights after landing; `r_band` runs the line forward to entry week.
  `scrubber_fault` 6–39 (`!fired crisis_air`), `crisis_air` / `dil_interlock`
  10–36, `h_pressure` 10–27.
- **Realism.** `storm_dose` "past a hundred millisieverts" (no regulatory
  comparison); `r_ghost` fifteen metres an hour; `r_pressure` leak detector,
  suit staged; `dil_dose` light-time per question; `m_overlay` fifteen seconds
  one way; `m_count` twenty-odd seconds; `w_mars_disc` thumb at the window;
  `dil_gains` alternate gain set with the owner's signature; `zip_back`
  "Before arrival"; `a_recall_marker` drops its time phrase.
- **Endings.** All six rewritten with names. `end_long_orbit` is a scene in
  week three of the orbit; `end_friend` has a real cost on the drive (no
  second try if it fails). Epilogue line for the late carrier: "Wanted to
  answer weeks early, then carried the answer the last stretch in person."
  Balance knobs used: `dust_report` weight 5 days 28/35, `dec_arrival` lean
  "warm wait hold", `comm_delay` weight 16 days 15–16.
- **Pacing.** `m_ripple` day 14, `m_alias` 20–21, `dec_signal` 20–23,
  `l_dock_hello` day 12, `dec_photo` 2–3, `w_venus_shadow` 7–18, `w_zodiac`
  8–20, `idle_spares` 13–39 (scrubber cartridge). Blank days ≤3%.
- **Humor.** `m_dropout` / `m_flash1` end flat; `a_last_night` drops
  "anyway"; `dil_interlock` override "Both sensors had a point".
  `g_news` names the neighbour as one of the first call's list, so `c_list`
  on day 42 still lands.

## Round 14 notes

- **Bugs.** `end_long_orbit` no longer mentions the struck tile (it named the
  wrong astronaut in most seasons and appeared when no tile was hit) or uses
  "nobody". New test `test_tile_and_eva_casting_over_300_seasons`: endings may
  not mention a tile or hinge line; any card naming one particular tile must
  cast the astronaut `r_strike` found it on; nobody injured by `crisis_eva` is
  sent outside afterwards (`dil_eva_cam` and `h_strike`/`r_strike` gate
  `!is A eva_who`). `when home A` on `c_dose` (now days 33–38), `l_crystals`,
  `h_band`, `h_flood`, `r_strike`; the presence test no longer exempts
  `r_strike`. `l_transfer` no longer crosses on day 2; `p_birthday` from day 8;
  `a_recall_shared` drops its EVA guard (the last pack always resolves);
  `dil_eva_cam` grammar.
- **Mechanism (fair, all seasons).** `a_report` is now an object: Cargo 2's own
  patch note (SURVEYED SITE = PAD · OBEY PAD CREW · KNOCK, LISTEN 1 TICK, KNOCK ·
  TIMEOUT: NONE) with the board's margin: divert, down whole, written off before
  the re-key, no orbiter but the dead relay ever had the channel, Earth fifteen
  minutes, tick eleven seconds. `m_reveal` ends "Ten point nine six: the
  lighthouse's number" (the old passes heard Cargo 2). `a_log` adds KEY UPDATE:
  NONE RECEIVED and counts ×350,000 hellos, eighteen ticks late at first.
  `a_window_quiet` ends on the ruling as one screen line. `m_alias` plants flat
  hour-to-hour residuals on day 20.
- **One light-time ladder (engineer's transfer model, matches STYLE).** Mars
  slide ~1.5 s/day at day 20; first hello round trip ~198 s (18 ticks) at day
  22; one-way just under half a minute at day 36 (`m_overlay`); round trip
  thirty-odd seconds at day 39 (`m_count`); 10 s round trip at day 41; Earth
  round trip fifteen minutes at day 40. `storm_dose` is "past fifty" (it can
  fire before any flare). `h_band` uses the orbiter's next pass, an hour later.
  `comm_delay` days 16–17.
- **Quieter.** `m_alias` loses "Anything aboard…/Not aboard, then";
  `c_theory` is the data only; `p_packer_note` "say hello to the hardware. Ours
  won't start till you do."; `h_voice` ends on the intercom clock reading
  tomorrow (r_voice's cause); `m_flash2` and `r_band` lose their nudges.
- **Flight rules.** `l_transfer` plants the read-back convention (the next ship
  reads back every critical command), reused in `dil_interlock`'s override and
  `end_lights`. `dec_arrival` is the crew's recommendation, which the flight
  director takes. `a_recall_wrist` gets the surgeon's clearance for the seat.
  `dil_gains` asks for the responsible engineer's signature.
- **Tics.** `a_log`, `g_packer`, `m_theory_confirm`, `hb_leaf`, `stash_found`
  fixed. `test_retired_tics_stay_retired` lints every card, option and system
  string for the STYLE retired list ("nobody", "reads it twice", taping or
  pinning things up, "galley wall", "go quiet", "since Starbase", "slowly",
  "doesn't mention", "Neither of them", "by itself", "it has moved", and a
  repeated "sleeve").
- **Small.** `m_listen` pays off `p_dream` ("like rain starting on a car
  roof"); `beat_haircut` aims the joke at the clippers; `zip_back` 30–39 and
  `c_dose` 33 thin day 34. Coda lines for the three answered endings, and the
  coda list now checks endings before `a_window_hail`.

## Round 15 notes

- **Casting (all checked by a new test).** Four dead vars freed (`t_signal`,
  `glints`, `t_dropout`, `t_call`; 30/32 used) instead of an engine change.
  `dec_arrival`'s wait option records `wait_who`; `end_long_orbit` B is now the
  one who actually argued to wait (it was right in about one season in five).
  `dust_worse` no longer hands the ruler to anyone. `p_packer_note` fires only
  when the stash is still held, to the holder, before `stash_found`; a new
  `p_packer_note_g` (galley log, no locker) covers the other seasons.
  `stash_found` records the last pack's hand (`stash_b`) and `a_recall_shared`
  gives the next pack to someone else. `water_fail` never sends the splinted
  wrist across. `dust_worse` waits four days after `dec_flash` (the only
  same-day decision pair; now 0/300). New test
  `test_ending_and_prop_roles_match_who_did_it_over_300_seasons`: every
  ending's A is the hello proposer, `end_long_orbit` B the wait voice,
  `end_through`/`end_lights` B the gust pilot, plus the locker, pack and wrist
  checks; it fails if `abort_who` is put back on `end_long_orbit`.
- **Reveal physics.** `m_reveal` is the orbiter's low-sun dawn pass: a long
  leaning shadow behind the rim, the knock pixel at its foot, the old landing
  ellipse, then the housekeeping (legs, half-open wing, dish on its stop). The
  "Ten point nine six" wink is gone. `a_window_quiet`: "two-year-old wait loop"
  and the ruling AFTER LANDING. LINE OF SIGHT, INSIDE THE TICK (no more "a suit
  beside it"; `end_through` answers from 200 m). `a_log` labels: HAIL RX ·
  LATE ×31,000 (Earth, 50–80 ticks behind), HELLO RX · NO CHALLENGE ×220,000,
  HELLO RX · LATE ×130,000 (seven ticks, then one), HELLO RX · OK. `m_key`:
  only the relay and the write-offs kept the key. `m_theory`: the spin is the
  ground's reading of three power-only passes. `r_dark`: the unseen challenge
  field hung the comms computer, then the backup.
- **`a_report`** is one board finding plus the patch, now ending ON HELLO: WAKE
  ALL, with the margin "Pad mode skips lost-link; the wake skips the battery
  check" and "Earth: fifteen minutes, there and back". `end_close` cites ON
  HELLO: WAKE ALL and "no battery check", matching the patch.
- **Light ladder.** `m_alias` nearly two seconds a day (flat residuals kept);
  `comm_delay` days 19–21; Mars at day 41 is three-quarters lit
  (`w_mars_disc*`); `storm_dose` days 15–20 (past 50 mSv from day 14).
  "Transfer window" → "crossing window"/"crossing" in cards, bible and STYLE.
  `l_transfer` prebreathes before crossing; `l_manifest` "scar on a survey
  frame".
- **Page = five days.** `c_hail` gives the span in days ("a hundred and twenty
  days back"), `a_descent_wait`/`_a` say "by the next log page", `a_log` drops
  per-page arithmetic. The page header itself is web's call: hand-off below.
- **Days 37–39.** `m_count` cut; `c2_clock` (day 39, mystery, cast to the flash
  owner): the cold gap ran forty knocks and the next knock came in weaker, so
  the beat runs out a few nights after landing. Restated knock totals cut from
  `c_hail`.
- **Endings.** *Through the Dust*: strut folded, the ship won't fly home; the
  one who wanted to answer climbs the rim two sols later and answers inside the
  tick from 200 m. *Old Friend*: the ground, eight minutes off, signs a waiver
  for the drive. *Long Orbit*: "Landed. All seven. The eighth was waiting."
  *Close Enough*: WAKE ALL wording. Winks cut from `m_flash1` (cosmic-ray hit),
  `c_theory` (now the microsecond timing: early, then late, once a day, the day
  37 minutes long) and `m_reveal`; `p_packer_note` softened.
- **Epilogue / system.** dose_ok thanks the ground; dose_swap moves on "a
  crewmate's better numbers". `dec_open` "Fleet vote, two pages. Both options
  are cleared; the flight director takes the call." `dil_open` "Private, for
  whoever looks after {A}:". Thirteen fold lines plural. One dark joke in entry
  week (`a_last_night`: "On the ground. One way or the other."). `h_flood` days
  8–27.
- **Gzip held** at 24,923 B (was 24,933) by trimming filler: `dec_signal`
  options, `dec_flash`, `dil_gains`, `valve_later`, `beat_window`,
  `storm_shelter`, `p_movie`, `earth_dot`, `photo_back`, `beat_coffee`,
  `clock_keep_back`, `sharpie2`, `w_sun_small`, `boiloff`, `dec_water`,
  `rescue_*`/`water_fail` ("in an unscheduled window"), `res_open`.
- **Declined.** Engine var-limit change (freed vars instead). Cutting
  `m_alias`'s flat residuals (other reviewers lean on them). Binding `p_dream`
  to `m_listen`'s cast. A hard cap on crowded days (max mystery cards on a
  day stays 3; no blank-day regressions). Any web edit.

### Web hand-off: page header (not built; web owns `web/render.js`)

Every page header reads "FLIGHT DAY NN", but one page is about five days of
real flight (`l_departure`, STYLE "Time"), so a numerate player reads "a
hundred and twenty days" on page 39 as a contradiction. Proposal: header
"LOG PAGE NN · DAYS a–b". Pages 1–6 (Earth orbit and the departure burn) are
one day each ("DAY 6"); `l_departure` says the five-day cadence starts after
it, so from page 7: a = 7 + 5·(NN−7), b = a + 4 (page 7 = days 7–11, page 42 =
days 182–186). Cheaper fallback: "LOG PAGE NN" with no day range. Same change in `sim/render.py` so
`tests/render_check.mjs` keeps matching. Keep "FLIGHT DAY" in the save/codes
UI only if it's an internal index.

## Round 16 notes

- **Concealment.** `m_checked`/`_g` drop the scar: "nothing on file near that
  pixel has power", the hopper "ninety kilometres south, its beacon as patchy
  as ever", two weeks of hails on the old key. The scar is explained once, in
  `a_report`, as the shed aft skirt. `m_dropout` says only "a little later each
  morning"; the 37 minutes stays in `c_theory` (day 38, 300/300).
  `m_theory_confirm`, `flash_answer_ground` and `m_flash2` stop dismissing the
  pixel with the same stock line. `h_band` ends "It could be cloud." `r_dark`
  and `r_dark_a` say "a link request with a field the new stack had never seen"
  (the word challenge waits for `m_key`).
- **WAKE ALL.** The patch says ON HELLO: WAKE ALL, so every answer is HELLO,
  then HOLD on the next tick: `a_window_hail` (wakes everything for one tick,
  then sleeps), `a_suit_plan` (procedure card), `end_through`, `end_close` (the
  HOLD never gets a listen), `end_patience`. "Safe hold" is gone.
  `a_window_quiet` ends UNDERSTOOD. COUNTING. New test
  `test_wake_all_is_always_followed_by_a_hold`.
- **Battery forecast.** `r_band` and `c2_cold` (mutually exclusive) say "a
  week or two after landing"; `c2_clock` (day 39) steepens it to "a few nights
  after landing, not weeks". It may only shorten: new test
  `test_battery_forecast_only_shortens`.
- **`a_report`** is now the board finding (standing on the surveyed site, the
  aft skirt, three passes that read the knock as spin, which answers why the
  ground went quiet for two years) plus the patch; the light-time and tick
  sums are gone ("works out where Earth is, and stops"). `a_log` keeps only the
  counters.
- **Numbers.** `comm_delay` days 17–21, "closing on two minutes each way"
  (engineer: 93–116 s at days 19–21). `storm_dose` days 17–21, "past a hundred
  millisieverts". Tick "about every eleven seconds" in `a_descent_hold_q`.
  `m_alias` "over a second and a half a day" (1.65 s/day at day 20).
  `w_phobos` under an hour behind the disc. The epilogue blackout line says
  nine seconds late, matching `e_entry_wait`. `a_descent_hold` demotes the
  beacon: radar for height, last orbiter fix for place, Cargo 2's radio to
  cross-check.
- **Endings.** Each closes on the loading bay's reply. `end_lights`: the crew
  watches the last lamp go out at noon. `end_long_orbit`: the hold draws less
  than the knocking did; the lamp cost the hold its heater. `end_friend`:
  battery past half at the halfway point, a stop at the drive-back limit, the
  waiver sixteen minutes later, the charge port fed off the half-open wing.
  `end_close`: Cargo 2 obeys WAKE ALL on the hello. `sys.end` "From the log:".
- **Casting and pacing.** `a_descent_wait*`, `w_mars_disc*` skip the dose
  owner; `a_log` skips the dose, abort and theory owners; `w_mars_disc*` skip
  the theory owner. No one now has three day-41 lines (was 11/300).
  `beat_cards` needs `!fired beat_coffee`, `p_movie` needs `!fired beat_cards`.
  Editor windows: `photo_back` 20–39, `earth_dot` 19–26, `g_count` 21–39,
  `gains_payoff` 19–39, `water_fail` 19–36, `p_garden_fail` 19–20,
  `l_handshake` 13–20, `dec_water` 13–26, `galley_pump` 14–39, `stash_found`
  23–31. `a_recall_shared` moves to day 38. `p_birthday` / `beat_haircut` say
  "happens to be aboard" / "aboard on a visit" (presence test covers both); new
  test `test_no_visit_lines_on_the_day_of_a_crossing`.
- **Craft.** `signal_reply`/`signal_echo` add a housekeeping counter (the
  deniable shiver for days 25–36). `sys.dec_open` "Fleet vote:"; `l_transfer`
  says votes are advice to the flight director. `g_count` "closes the lid on
  the count"; `hb_leaf` to the thigh pocket; `p_garden_none` ends "Seeds keep.";
  `g_news` a retirement party. The garden epilogue plants "in the lee of the
  ship".
- **Declined.** p36 Mars "about a minute" (reference ephemeris: 29.4 s one-way,
  so "just under half a minute" stays). The two-year-silence line in
  `m_theory` (too strong a day-17 clue; it lives in `a_report`). The hunter's
  `g_packer` clause (a WHO clue). `beat_watch` "a seventh of the Moon" (the
  engineer's figures support "less than half"). Moving `a_recall_home/plan` to
  day 41 (day 41 is full; `a_recall_shared` moved to 38 instead).

## Replay: the mystery spine reads the same every season (note, not built)

Casting changes per season, but the spine (carrier → alias → relay → dropout →
flash → key → overlay → reveal) is the same text, so a second season reads as
a rerun. Options, cheapest first:
1. **Phrasing variants.** Two or three texts per spine beat, picked by a voyage
   key bit (`when is`/flag set at day 1 from the key). Same facts, same days,
   different objects and voices. Costs text bytes (roughly +3–5 KB gzip for
   the twelve core beats), no engine change.
2. **Season-2 decoy swap.** Keep the truth, rotate the decoy (hopper one season,
   a second write-off another) and which camera or instrument first sees the
   light. Needs a few alternate cards and fair-play test cases per variant.
3. **Season-2 truth variant.** A different first-batch vehicle or a different
   escaped requirement with the same tick mechanic. Biggest payoff, biggest
   cost: new plants, new reveal, new endings, a fresh blind review.
Recommendation: (1) for season 2, keyed so a returning player never gets the
same phrasing twice in a row; leave (3) for a sequel.

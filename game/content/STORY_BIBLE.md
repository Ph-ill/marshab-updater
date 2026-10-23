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
   answered) and the descent call (`a_descent_*`); day 42 the recall cards and
   the ending. Thread beats (`c_*`, cat human) keep days 34–42 at two or more
   story cards a day (tested over 300 seasons).
   `test_climax_is_clear` and the 300-season test enforce it.

## The ramp (slow burn)

| Phase | Mystery content |
|---|---|
| 1 (days 1–10) | No mystery cards. The two phase-1 core clues hide in ordinary life (`l_reboot` day 3, `l_manifest` day 5). |
| 2 (days 11–24) | The carrier (`m_carrier`, due days 15–19) on the spare dish parked on Mars, called an alias, then retracted (`m_alias`, days 18–19, opens `dec_signal`). The ripple (`m_ripple`, a coolant-pump control loop at 0.09 Hz). The 37-minute dropout (`m_dropout`). The crew's theory (`m_theory`, day 22): a written-off relay in a one-sol orbit, in a reset loop. |
| 3 (days 25–36) | The theory confirmed (`m_theory_confirm`, the decoy holds). The reply (`signal_reply` / `signal_echo`). The uncanny hooks (ghost, voice, dark from day 25; band from day 30). The flash (30), the second sighting and its vote (32), the key (34), the ground answer (35), the overlay (36). |
| 4 (days 37–42) | Checked (the ground hails), listen, count, the reveal (40), the window (41), the entry scene and endings (42). |

Measured (lvc ramp line): mystery cards by first day 0 / 6 / 17 / 6. Per season
(metrics, 300 seasons): 0.0 / 5.6 / 10.0 / 4.0 mystery cards fired by phase.

## The twist, in layers

**Outer layer (what the crew believes from day 22):** something out there is
boot-looping. The decoy is a written-off relay orbiter in a one-sol orbit,
resetting forever; its 37-minute daily drift and half-orbit dropouts fit the
evidence (`m_dropout`, `m_theory`, `m_theory_confirm`, `r_band`).

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
escalate. The landing interlock then waits about eleven seconds for a signed
answer to that challenge before the watchdog fires again. Earth hailed it for
six weeks on the normal uplink (it heard every one on its low-gain antenna), but
Earth was always minutes away, so every reply answered a challenge that no
longer existed: the event recorder logged each `HELLO RX · REPLAY · DISCARD`.
Its own replies only ever went out on the old band.

**The 10.96 s coincidence, resolved:** in the weeks after the landing, Earth's
big dishes did hear flashes on the old band, every 10.96 s, and attributed them
to the tumbling relay. That is where the catalogue's "spin" for the relay comes
from (`m_theory`: "going by RF flashes heard in the weeks after it failed"), and
why both were written off (`a_report`: "old-band carrier, attributed to relay
tumble"). `c_theory`'s "Same keeper?" is answered by that line.

**The window (day 41, fleet time):** the fleet is about 5.4 light-seconds out.
Knock at 04:10:07; heard 5.4 s later; the standing auto-answer (a signed standard
handshake) lands 10.94 s after the knock, on the beat, in real time, twenty
milliseconds inside the 10.96 s window. `HELLO RX · OK`. One tap is enough. In
the log-it branch: "The knock lasts eleven." The reader does the subtraction.

**Why nobody caught it (each gap has an in-world reason):**

| Who | What they saw | Why it didn't add up |
|---|---|---|
| Earth (comms) | Six weeks of ground hails, no acknowledgement | Every answer arrived minutes late and was discarded; Cargo 2's replies went out only on the old band, which Earth stopped listening to; X-band OVERTEMP, dish jammed (`m_checked`, `a_report`) |
| Earth (old band) | Flashes every 10.96 s in the first weeks | Attributed to the tumbling relay, written into its catalogue entry as a spin rate (`m_theory`, `a_report`) |
| Earth (security) | Signed link requests, sequence number 1 | Looks like a stolen key or a replay: "Not ours.", key rotation opened (`m_key`, `r_dark`), quietly deferred to after landing (`c_hail`) |
| Orbiter imaging | One coarse afternoon frame: a smudge and a streak | Backup-site maps predate the cargo landings (`dec_name`); from straight above a standing Starship is two pixels and a shadow; day 40 is the first sharp pass since (`m_reveal`) |
| The fleet, first look | A carrier on the dish, too faint to lock | Decoy 1: an alias of something aboard (`m_carrier`), killed when it lands on two ships' unsynchronised machinery in the same millisecond (`m_alias`) |
| The fleet, middle | 37-minute drift, out of view half the day | Decoy 2: the spinning relay "lighthouse" (`m_theory`, `m_theory_confirm`) |

**Control clues (the fair test):** `m_alias` shows the bursts are external
(simultaneous on two ships); `m_theory_confirm` admits the relay is behind Mars
for "an hour or so", not half a day; `c_theory` compares the swings (a relay
would drag the knocks by most of a tenth of a second each orbit, ±68 ms; these
swing by a hundredth once a day, ±11 ms: the size of Mars, turning);
`r_band` keeps one clue only, the fixed byte cutoff.

**Plants for the why:** the galley chime and counting to eleven (`l_reboot`),
the galley screen that waits for the ground's hello (`l_handshake`), the
comm-delay cards (`comm_delay`, `comm_delay2`, `h_silence`), "the interlock
won't move until they agree" (`dil_interlock`), the system text "One tap is
enough". The reveal has a crewmate counting to eleven, humming the chime.

**The vote that matters:** `dec_signal` (days 18–19, after `m_alias`).
*Answer every burst* sets a standing reply, the standard handshake signed with the old program key (costs:
comms-computer time, letters wait); then `a_window_hail` (day 41) lands the
answer in time, `a_log` plays the event recorder (Earth's hellos, then most of
a million late fleet answers, then `HELLO RX · OK`), and the light stops
blinking. *Log it* means `a_window_quiet`: "The knock lasts eleven." Mission
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
has no member fired before the reveal day. Measured: 300/300 seasons, 8 groups.

| # | Card | Phase | Core | Surface | Truth |
|---|---|---|---|---|---|
| 1 | `l_reboot` | 1 | yes | A galley update, an in-joke about the chime | A boot is eleven seconds |
| 2 | `l_manifest` | 1 | yes | Background: the cargo ships and a longer written-off page (drill rig, nitrogen pallet, Cargo 2, weather orbiter, grey relay) | Cargo 2 and its shadow, outside the zone |
| 3 | System text `res_open` | all | – | UI copy | One tap is enough |
| 4 | `m_carrier` | 2 | yes | An old probe's beacon on the old channel | Cargo 2, every 10.96 s |
| 5 | `m_ripple` | 2 | – | A coolant-pump control loop hunting | The same rhythm in the noise floor |
| 6 | `m_dropout` | 2 | yes | Gone 37 minutes later each day: a one-sol orbit | Mars's own day: it turns with the ground |
| 7 | `m_theory_confirm` | 3 | – | The decoy confirmed | The decoy |
| 8 | `r_band` (days 31–34) | 3 | – | A safe-mode beacon, still the relay | Cut at the same byte every time, before the spacecraft ID |
| 9 | `m_flash1` | 3 | yes | A pixel on the night side | The floodlights at power-up |
| 10 | key: `m_key` / `r_dark` | 3 | yes | A replay: "Not ours. Checked." | A trusted key: it's one of ours |
| 11 | ground: `flash_answer` / `flash_answer_ground` | 3 | yes | It isn't in orbit | The decoy breaks |
| 12 | `m_overlay` | 3 | yes | Carrier and flash share a clock | The same machine |

Misdirections: `m_carrier` ("an alias, something of ours"; retracted by
`m_alias`, not a clue), `m_theory` / `m_theory_confirm` (the relay), `w_phosphene`
(cosmic-ray pixels), `r_band` (old relay), `r_ghost` (a cover plate shed at
departure, still flying with them), `m_key` / `r_dark` ("Not ours. Checked."),
`signal_reply` (cut off before the sender field; it no longer claims a timing
change, so every branch agrees the averaged beat never moves).

## The reveal itself

`m_reveal` (`reveal`, day 40) is cast to the theory owner (`ow_theory`);
`m_reveal_any` is the fallback and never fires in 300 seasons. Understated: the
first sharp pass since before the cargo ships flew, Cargo 2 named once, dish
jammed against its stop, floodlights at power-up, the galley chime fitting the
gap. `a_report` (day 40) carries the sting and the root cause: relay lost on
the landing pass, OVERTEMP, six weeks of ground hails, carrier attributed to
relay tumble; a page and a half / forty pages ("watchdog", "what lives in RAM").

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
| hail | `m_carrier` (15) → `m_alias` → `dec_signal` (18) | `signal_reply`/`signal_echo` (28), `m_overlay` (36), `c_hail` (39), `a_window_*` + `a_log` (41) |
| theory | `m_theory` (22) | `m_theory_confirm` (25), `c_theory` (38), `m_reveal` (40), `a_recall_marker` (42) |

Each owner has one spoken line and one wrong-then-recover moment, usually in
the `c_*` beat (days 34–39, cat human so the one-mystery-a-day rule holds):
the hail owner's "Not us. Ignore my last.", the lost-then-found letter, the
tank argued for then pumped, the missing name added, the fifth bar played
wrong, the seedling put in the locker then taken back out, the lighthouse
redrawn. The packer has a setup (`p_packer_note`, day 16–17) before `g_packer`.

**Lasting cost:** the 02:00 thruster hook (`h_thruster` → `r_thruster`) leaves
the valve isolated: propellant, `valve_later` (24–33), and on day 42
`a_recall_valve`, the ship flying through blackout one thruster short.

**The climax on the page (day 42):** `idle_mentor` binds `abort_who` (the one
drilled on the manual landing abort). `a_descent_hold` (41) has them run it
"from memory"; then one entry scene per branch, cast to them: `e_entry_hold`
(blackout, brown cameras, a gust, the call not made), `e_entry_wait`
(aerocapture, out of blackout eleven seconds late), `e_entry_clear` (an engine
lights a half second late). The endings then pick up the landing.

**Voices (per arc, not per person):** list-keeper talks through the gaps;
song never explains ("Planet first."); letter-keeper is procedural about
everything except the letter, which is never logged; garden logs failure
hopefully; dose is proud and has to be asked twice ("Thanks for checking.");
lighthouse draws in blue marker; auto-answer logs to the millisecond, then
says "Hi" out loud, ten seconds early.

Costs carry forward: answering costs letters (morale), leaving the flash buys
them back, rationed water costs the garden, the wait branch costs fuel and food.
Endings cite the votes. The packer's loss is on the page (`g_packer`).

## Endings: hail × arrival (the core truth never changes)

Checked in deck order on day 42; first match wins. Titles come from `title`
(text.json `ti`). Every ending closes on the first crate ("You'll thank me.")
and the first message off the surface, to a loading bay at Starbase:
"Landed. All eight." Endings may run to 640 characters (lint MAX_ENDING).

**Geometry:** day 41 is about four days before atmospheric entry. Hold the plan
= retarget to the backup site, about three kilometres from Cargo 2, with radar
for height and Cargo 2 as the place marker (answered: a ranging tone).
Aerocapture = four nights in a long orbit, then the prime zone and a rover
drive (Cargo 4's rover). Clear air = prime zone, Cargo 2 thirty kilometres
past it, drive out. Unanswered endings answer "from close enough" in person.
Elapsed time since Cargo 2 landed: two years, everywhere.
Each needs ≥ 5% of 300 seasons (tested).

| # | Ending | Condition | Measured |
|---|---|---|---|
| 1 | *Lights On* (`end_lights`) | answered + held the plan | 20.3% |
| 2 | *Through the Dust* (`end_through`) | held the plan | 19.7% |
| 3 | *The Long Orbit* (`end_long_orbit`) | answered + aerocapture and wait | 17.3% |
| 4 | *Patience* (`end_patience`) | aerocapture and wait | 19.7% |
| 5 | *Old Friend* (`end_friend`) | answered, clear air | 10.0% |
| 6 | *Close Enough* (`end_close`) | clear air, not answered | 13.0% |

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
(every fifth day from day 7) or an unscheduled rescue window. Skill flavor stays
subtle, in no more than about 1 card in 6.

## Cliffhangers

Mystery hooks (ghost, voice, dark) open days 25–33, band 30–33, and all resolve by 34.
Other hooks open by 35 and resolve by 36. Each resolves in grounded hardware
with a residue.

## Reserved words

engagement keeps `content/engage/reserved.json`: story words that engagement/UI
text must not use. That file lives on the engagement branch only, so this list is
the source to sync from. "Cargo 2" stays as the story's name.

Cargo 2, smudge, streak, shadow (of a ship), fingers crossed, self-test,
safe mode, safe-mode, pixel, night frame, fast sequence, spin, turns a minute,
between boots, old channel, retired channel, old common channel, aim for the
light, eleven / 11 seconds, 10.96, Sharpie, you'll thank me, written off, lost
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
The knock lasts eleven, most of a million, half the day, abort call, keeper,
Same keeper, Wrong lighthouse, eight and a half degrees, I'll be counting.

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
   count (39), reveal (40); day 41 the window (`a_window_*`) and the descent
   call (`a_descent_*`); day 42 the recall cards and the ending.
   `test_climax_is_clear` and the 300-season test enforce it.

## The ramp (slow burn)

| Phase | Mystery content |
|---|---|
| 1 (days 1–10) | No mystery cards. The two phase-1 core clues hide in ordinary life (`l_reboot` day 3, `l_manifest` day 5). |
| 2 (days 11–24) | The carrier (`m_carrier`, due days 15–19, opens `dec_signal`) on the ship-to-ship receiver. The ripple (`m_ripple`, a coolant-pump ground loop at 0.09 Hz). The 37-minute dropout (`m_dropout`). The crew's theory (`m_theory`, day 22): a written-off relay in a one-sol orbit, in a reset loop. |
| 3 (days 25–36) | The theory confirmed (`m_theory_confirm`, the decoy holds). The reply (`signal_reply` / `signal_echo`). The uncanny hooks (band, ghost, voice, dark). The flash (30), the second sighting and its vote (32), the key (34), the ground answer (35), the overlay (36). |
| 4 (days 37–42) | Checked, listen, count, the reveal (40), the window (41), endings. |

Measured (lvc ramp line): mystery cards by first day 0 / 5 / 17 / 6. Per season
(metrics, 300 seasons): 0.0 / 4.6 / 9.9 / 4.0 mystery cards fired by phase.

## The twist, in layers

**Outer layer (what the crew believes from day 22):** something out there is
boot-looping. The decoy is a written-off relay orbiter in a one-sol orbit,
resetting forever; its 37-minute daily drift and half-orbit dropouts fit the
evidence (`m_dropout`, `m_theory`, `m_theory_confirm`, `r_band`).

**Truth (day 40):** it's on the ground. Cargo 2 came down about thirty
kilometres long, tilted behind a crater rim, one solar wing half open, its dish
aimed at empty sky. Its flight computer reboots every eleven seconds; each boot
keys the beacon once and blinks the landing lights once (the self-test).

**Why it never stopped (hindsight):** after a boot, its landing interlock waits
about eleven seconds for a peer to answer before it gives up and reboots. Earth
was always minutes away, so every reply from home arrived to a machine that had
already given up. The fleet, inside five light-seconds on day 41, is the first
thing in years that can answer in time. One tap is enough.

**Plants for the why:** the galley chime and counting to eleven (`l_reboot`),
the galley screen that waits for the ground's hello (`l_handshake`), the
comm-delay cards (`comm_delay`, `comm_delay2`, `h_silence`), "the interlock
won't move until they agree" (`dil_interlock`), the system text "One tap is
enough". The reveal has a crewmate counting to eleven, humming the chime.

**The vote that matters:** `dec_signal` (day 15). *Answer* means the hail owner
hails every pass (costs: letters wait); then `a_window_hail` (day 41) lands the
answer in time and the light stops blinking. *Log it* means `a_window_quiet`:
"Tomorrow, then. In person." The `dec_flash` vote (look / leave) changes who
learns it's on the ground and how (`flash_answer` vs `flash_answer_ground`,
`m_checked` vs `m_checked_g`); leaving it buys letters on time.

## Motifs

| Motif | Planted | Turns | Pays off |
|---|---|---|---|
| **The thumb** | Early watch: Earth spills out around a thumb | Middle watch: a thumbnail covers Earth | Day 41: Mars spills out around it again, and a light keeps time |
| **Eleven** | The galley chime; the fleet counts to eleven | The carrier's 10.96 s; the interlock | A crewmate counts to eleven, humming the chime |
| **The Sharpie hand** | The ration stash ("you'll thank me", a little ship, fingers crossed) | A spare not on the manifest; `sharpie2` | The crate coda in every ending |
| **What earlier missions left** | The manifest: Cargo 1/3/4 and one line for Cargo 2 | The relay decoy, the cover plate | Cargo 2, behind the crater rim |
| **The delay** | A live call, laughter landing in real time | A minute, then six, then ten | Earth's answers always came too late |
| **The garden** | Seeds in the first week | Four pods fail | A shoot on the approach, unless the water was rationed |
| **The shelter between the water tanks** | Flare drills | The dose thread | Patting the tanks goodnight on the last night |

## Fair-play clues (surface → truth)

**Core clues** carry `clue core [GROUP]` (lvc). text.json `core` is a list of
groups; `sim/season.py --seasons 300` and the 300-season test fail if any group
has no member fired before the reveal day. Measured: 300/300 seasons, 8 groups.

| # | Card | Phase | Core | Surface | Truth |
|---|---|---|---|---|---|
| 1 | `l_reboot` | 1 | yes | A galley update, an in-joke about the chime | A boot is eleven seconds |
| 2 | `l_manifest` | 1 | yes | Background: the cargo ships, one written off, a smudge-and-streak thumbnail | Cargo 2 and its shadow, outside the zone |
| 3 | System text `res_open` | all | – | UI copy | One tap is enough |
| 4 | `m_carrier` | 2 | yes | An old probe's beacon on the old channel | Cargo 2, every 10.96 s |
| 5 | `m_ripple` | 2 | – | Coolant-pump ground loop | The same rhythm in the noise floor |
| 6 | `m_dropout` | 2 | yes | Gone 37 minutes later each day: a one-sol orbit | Mars's own day: it turns with the ground |
| 7 | `m_theory_confirm` | 3 | – | The decoy confirmed | The decoy |
| 8 | `r_band` | 3 | – | Matched to the old relay, almost | Cut before the spacecraft ID |
| 9 | `m_flash1` | 3 | yes | A pixel on the night side | The landing lights |
| 10 | key: `m_key` / `r_dark` | 3 | yes | A replay: "Not ours. Checked." | A trusted key: it's one of ours |
| 11 | ground: `flash_answer` / `flash_answer_ground` | 3 | yes | It isn't in orbit | The decoy breaks |
| 12 | `m_overlay` | 3 | yes | Carrier and flash share a clock | The same machine |

Misdirections: `m_theory` / `m_theory_confirm` (the relay), `w_phosphene`
(cosmic-ray pixels), `r_band` (old relay), `r_ghost` (a cover plate shed at
departure, still flying with them), `m_key` / `r_dark` ("Not ours. Checked."),
`signal_reply` (cut off before the sender field).

## The reveal itself

`m_reveal` (`reveal`, day 40) is cast to the theory owner (`ow_theory`);
`m_reveal_any` is the fallback and never fires in 300 seasons. Understated: the
survey frame, Cargo 2 named once, the count to eleven, "the streak was its
shadow". `a_report` (day 40) carries the sting: a page and a half / forty pages.

## Threads (seven, one owner each per voyage)

Owners are bound with `who` on the opener and kept distinct with `!is`, so all
seven astronauts carry exactly one thread and every one gets an epilogue line.

| Thread | Opener (day) | Payoffs |
|---|---|---|
| list | `p_live_call` (1) | `p_list_letter`, `g_news` (27), `a_list` (42) |
| song | `p_music` (2) | `p_song_ask` (21), `a_song` (42) |
| garden | `p_garden_plant` (4) | `p_garden_fail` (18), `p_garden_sprout` or `p_garden_none` (water vote) |
| letter | `l_letter` → `dil_letter` (8) | `letter_open` / `letter_worn`, `a_letter` (40) |
| dose | `l_dose` → `dil_dose` (9) | `dose_swap` / `dose_ok`, `a_last_night` (41) |
| hail | `m_carrier` → `dec_signal` (15) | `signal_reply`/`signal_echo` (28), `m_overlay` (36), `a_window_*` (41), `a_recall_*` (42) |
| theory | `m_theory` (22) | `m_theory_confirm` (25), `m_reveal` (40) |

Costs carry forward: answering costs letters (morale), leaving the flash buys
them back, rationed water costs the garden, the wait branch costs fuel and food.
Endings cite the votes. The packer's loss is on the page (`g_packer`).

## Endings: hail × arrival (the core truth never changes)

Checked in deck order on day 42; first match wins. Titles come from `title`
(text.json `ti`). Every ending closes on the first crate (the Sharpie coda).
Each needs ≥ 5% of 300 seasons (tested).

| # | Ending | Condition | Measured |
|---|---|---|---|
| 1 | *Lights On* (`end_lights`) | answered + held the plan | 15.7% |
| 2 | *Through the Dust* (`end_through`) | held the plan | 22.0% |
| 3 | *The Long Orbit* (`end_long_orbit`) | answered + aerocapture and wait | 19.3% |
| 4 | *Patience* (`end_patience`) | aerocapture and wait | 16.0% |
| 5 | *Old Friend* (`end_friend`) | answered, clear air | 12.7% |
| 6 | *Close Enough* (`end_close`) | clear air, not answered | 14.3% |

## Epilogue

`system.json` `epi.story` is a priority list of [card id, line]: thread payoffs
first, then openers, then a few fallbacks. lvc maps it to card indices.
`Renderer.epilogue` gives each astronaut the first line whose card they were
role A in. Measured: 7/7 in 300/300 seasons (tested).

## Reading view

`Renderer.reader` (sim/out/reader.txt) folds each day's system echoes (actions,
crossings, notes) into one "around the fleet" line and prints the ending title
as a heading. Hand-off: web/render.js should do the same.

## The second read

Every clue card carries `clue`; text.json `reread` lists them. The end screen
can list the flight days they fired on, with no explanation.

## Characters

All seven are competent, kind, and tired in different ways. Each astronaut
belongs to a home ship; a ship may briefly hold 0 or 2 during a transfer window
(every fifth day from day 7) or an unscheduled rescue window. Skill flavor stays
subtle, in no more than about 1 card in 6.

## Cliffhangers

Mystery hooks (band, ghost, voice, dark) open days 25–33 and resolve by 34.
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
chime, count to eleven, offline mode, replay, not ours, say again, keeps time.

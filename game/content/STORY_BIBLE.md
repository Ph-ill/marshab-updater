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

1. **Leaving (days 1–10).** Days 1–5 are in Earth orbit (fuelling, tanker
   dockings, checkouts): Earth fills the window and calls home are live. The
   departure burn is day 6 (`l_departure`), and only after that does Earth
   start to shrink. Plant everything here.
2. **The middle dark (days 11–28).** Earth becomes a dot. Calls turn into
   letters. The routine hardens into rituals, the isolation bites, and the
   carrier and the flare nights come. The garden fails here.
3. **The approach (days 29–39).** Mars becomes a disc, then a place. The things
   earlier missions left behind start to answer. The dust storm builds and
   forces the arrival vote (`dust_worse` opens `dec_arrival`).
4. **Arrival (days 40–42).** Quiet on purpose: no new hooks, threads or
   filler. Day 40 the reveal, day 41 the descent call (one of three
   `a_descent_*` cards), day 42 the ending. `test_climax_is_clear` enforces it.

## The ramp (slow burn)

| Phase | Mystery content |
|---|---|
| 1 (days 1–10) | No mystery cards. The two phase-1 core clues hide in ordinary life (`l_reboot` days 2–9, `l_manifest` days 4–9), alongside the thumb, the garden and the live call. |
| 2 (days 11–24) | The carrier (`m_carrier`, a due event days 13–16 that opens `dec_signal`), which reads as a retired probe's beacon. The noise-floor ripple, which reads as a wheel harmonic. The crew's orbiter theory (`m_theory`, days 17–24) lands here, so a sharp reader's day-20 lead is the misdirection. Phosphenes (single cosmic-ray pixels, filed `grim`) prime the cosmic-ray reading of the flash. |
| 3 (days 25–36) | The carrier comes back cut off mid-header. The uncanny hooks open up (band, ghost, voice, dark). The flash (`m_flash1`, due days 29–32), the second sighting, and the vote on it. The crew stops being able to call it chance. |
| 4 (days 37–42) | The overlay. The reveal (day 40, every season). The endings. |

Measured (lvc ramp line): mystery cards by first day 0 / 4 / 13 / 3.

## Motifs

| Motif | Planted | Turns | Pays off |
|---|---|---|---|
| **The thumb**: holding a thumb up to a world | The early watch: Earth won't fit behind a thumb | The middle watch: a thumbnail covers Earth | Approach: Mars no longer fits behind it |
| **Eleven seconds** | A galley screen reboot: dark, logo, chime, over before anyone counts to eleven | The carrier ("every 11 seconds"), a noise ripple, the orbiter theory ("eleven seconds a turn") | The boot loop: the lights blink again eleven seconds later |
| **The Sharpie hand**: someone at Starbase packing a margin | The ration stash ("you'll thank me", a Starship doodle with its fingers crossed) | A spare that isn't on the manifest | A second note in the same hand, at the moment it's needed most |
| **What earlier missions left** | The breakfast manifest line | The beacon hook, the spent stage | Cargo 2, waiting at the landing zone |
| **The delay** | A live call home, with laughter landing in real time | Letters, then monologues | A message that arrives after the moment it was about |
| **The garden** | Seeds planted in the first week | Nothing grows, and the crew keeps watering it anyway | One shoot on the approach, carried down |
| **The shelter between the water tanks** | Flare drills, a deck of cards | Flare nights, shoulder to shoulder | Water is shielding, water is life, water is the last thing checked before landing |

## The reveal (designed first; everything else works backwards from it)

### Candidates, and the skeptical reader's attack

**A. The lighthouse.** The carrier and the night-side flashes both come from a
dead orbiter tumbling with an 11-second rotation.
- *Guessable by day 20?* Yes, and that's the point now: `m_theory` hands it to
  the reader on days 17–24 with a measured spin rate that fits the carrier.
- *Cheat?* No, but it isn't a twist. The reveal would just confirm the surface
  reading.
- *Reframes earlier moments?* Barely.
- *Grounded?* Yes.
- *Emotional?* Melancholy, but it's about a machine nobody aboard knew.
- **Verdict: weak as the reveal, strong as the misdirection.** Kept as the
  crew's own theory.

**B. The packer.** One person at Starbase staged every oddity (the stash, the
voice, the antenna file) as a long-distance care package.
- *Guessable?* Partly. The Sharpie notes point at it.
- *Cheat?* Yes. The antenna file and the flashes on Mars can't be explained by
  someone on Earth without hand-waving.
- *Reframes?* The kind moments, yes. The uncanny ones, badly.
- *Grounded?* Strained.
- *Emotional?* Warm, but it shrinks the dread into a prank.
- **Verdict: rejected.** The packer survives as a person, not as the
  explanation.

**C. An echo.** The carrier is the fleet's own transmissions, reflected back
from Phobos or from their own discarded hardware.
- *Guessable?* Unlikely.
- *Cheat?* Yes. A reflection doesn't make an 11-second rhythm or a light on the
  night side.
- *Grounded?* Not really.
- *Emotional?* Hollow.
- **Verdict: rejected.**

**D (chosen). Cargo 2.** One of the uncrewed cargo Starships that went ahead was
written off as "lost on landing" years ago. It isn't lost. It landed upright at
the edge of the landing zone with a dead uplink. Its flight computer has been
stuck in a watchdog boot loop ever since.
- Every boot takes eleven seconds. Every boot keys the beacon once, on the old
  fleet channel, and blinks the landing lights once for the self-test.
- So the carrier and the night-side flashes are the same machine, saying "I'm
  here" the only way it can, every eleven seconds, for years.
- It carries what the manifest said it carried: spares and water. In other
  words, the margin.

The attack on D:
- *Guessable by day 20?* Very unlikely. By then the clues are a breakfast
  manifest line, a galley screen that blinks the lights when it restarts, a
  Sharpie doodle and a carrier on an unused frequency. Each one has an ordinary
  reading. The obvious theory (A) arrives later and fits well enough to stop
  people looking.
- *Cheat?* No. Every piece is on the page:
  - the eleven seconds;
  - the boot blink;
  - the written-off cargo ship;
  - the flashes on the ground, not in orbit;
  - a command carrying a valid fleet signature from no ship in the fleet.
- *Reframes?* Hard. Read again, the galley reboot is the whole answer. The
  doodle on the stash bag is a ship with a 2 on it. "One tap is enough" stops
  being UI copy.
- *Grounded?* Uncrewed cargo Starships going ahead of crew is the public plan.
  A lander with a failed antenna and a computer in a boot loop is an ordinary
  failure, held for an unusual length of time. Controls people will feel this
  one in their teeth, and nobody has to say why.
- *Emotional?* Yes. A machine built by people the crew knows has been keeping a
  light on at the landing site for years. It holds the margin someone at
  Starbase packed after losing it. The fleet arrives as its rescue, not its
  discoverer.

**Why D wins:** it's the only candidate that makes the dread *and* the wonder
true at once. Some weeks of the voyage felt haunted, and they were. The ghost
is ours, and it has been waiting.

### Fair-play clues (surface reading → truth)

**Core clues** carry `clue core` (lvc). They go into text.json as `core`, and
`sim/season.py --seasons 300` (and `test_fair_play_and_endings_over_300_seasons`)
fails if any season reaches the first `reveal` card without all of them fired on
an earlier day. Measured: 300/300 seasons. Core clues are due cards with tight
windows; decisions they need are opened from an event with `do open`.

| # | Card / place | Phase | Core | Surface | Truth |
|---|---|---|---|---|---|
| 1 | `l_reboot` | 1 | yes | A galley screen update; a cabin in-joke about the chime | A boot is over in under eleven seconds |
| 2 | `l_manifest` (tanker docking, Earth orbit) | 1 | yes | Background color: the cargo ships went ahead, one written off, with a smudge-and-streak thumbnail | Cargo 2 exists, carried spares and water, and the thumbnail is the ship and its shadow |
| 3 | System text `res_open`: "Anyone can answer this one. One tap is enough." | all | – | UI copy for rescues | In the answered endings, one hail was enough |
| 4 | `m_carrier` → `dec_signal` | 2 | yes | "Some retired probe's beacon", every 11 seconds, on a channel the fleet retired | It's the old fleet channel |
| 5 | `m_ripple` | 2 | – | A reaction wheel harmonic | The boot cycle, heard in the noise floor |
| 6 | `r_band` | 3 | – | A safe-mode beacon matched to a science orbiter | The header format is a Starship's |
| 7 | `r_dark` | 3 | – | Hacking or a ground-side mistake; a replayed packet "it has said before" | The fleet software accepted it as one of ours |
| 8 | `m_flash1` | 3 | yes | One lit pixel in an orbiter night frame: a cosmic ray, probably | The landing lights |
| 9 | `flash_answer` | 3 | – | (if they looked) Frames counted | It's on the ground, not in orbit: the orbiter theory breaks |
| 10 | `m_overlay` | 4 | – | The carrier and the flash share a frame | The same machine |

`sharpie2` (days 26–39) is where the 2 appears in the Sharpie hand; it echoes the
stash and isn't counted. `dil_stash` is no longer a clue.

**Misdirections:**
- `m_theory` (phase 2): the crew's spinning relay orbiter. Its measured turn
  fits the carrier exactly, so everyone relaxes.
- `w_phosphene` (phase 2): cosmic rays as single pixels, so `m_flash1` reads as
  noise.
- `r_band` (phase 3): matched to a science orbiter in safe mode.
- `r_ghost` (phase 3): a real tumbling stage. It proves tumbling hardware is
  out there.
- `signal_reply` (phase 3): half a frame, cut off mid-header, "as if the sender
  restarted". It reads as the orbiter's spin taking the antenna away.
- `r_dark`: the replayed packet reads as a stuck relay.

### The reveal itself

`m_reveal` (`reveal`) fires on flight day 40, cast to whoever saw the flash
(`flash_who`); `m_reveal_any` is the fallback if that card can't fire, and
normally never does. It's understated: the landing-zone survey comes in sharp,
the thumbnail's smudge and streak become Cargo 2 and its shadow, and the lights
blink again eleven seconds later. It names Cargo 2 once and explains nothing
else.

### Endings: carrier × arrival (the core truth never changes)

Checked in deck order on day 42; the first match wins. Each needs ≥ 5% of 300
seasons (tested).

| # | Ending | Condition | Measured |
|---|---|---|---|
| 1 | *Lights On* (`end_lights`) | answered the carrier + held the plan | 18.7% |
| 2 | *Through the Dust* (`end_through`) | held the plan | 22.0% |
| 3 | *The Long Orbit* (`end_long_orbit`) | answered + waited in orbit | 18.0% |
| 4 | *Patience* (`end_patience`) | waited in orbit | 14.0% |
| 5 | *Old Friend* (`end_friend`) | answered, no arrival vote | 11.7% |
| 6 | *The Long Way Round* (`end_long_way`) | none of the above | 15.7% |

### Epilogue

`system.json` `epi.story` is a priority list of [card id, line]. lvc maps it to
[card index, line]. `Renderer.epilogue` gives each crew member the first line
whose card they were role A in, falling back to the axis/bond lines.
`sim/season.py` writes it to `sim/out/epilogue.txt`. The web end screen
should mirror `Renderer.epilogue` (web worker).

### The second read

Every clue card carries `clue` (lvc). The list goes into text.json as `reread`
(card indices in deck order). The end screen can list the flight days on which
those cards fired, read from the story log, with no explanation: "Flight days
worth a second look: 3, 6, 14, …". That's data only, and the UI is the web
worker's call. The final entries should send the reader back to scroll.

## Threads

- **The garden**: a planting beat (first week), a failing beat (the middle
  dark), then one sprout (approach), only if someone kept watering it (the
  `garden` var).
- **The flashes**: the first sighting (due, days 29–32); a second sighting at the
  same longitude a few days later; then a fleet vote (look closer / leave it
  for the ground); then a resolution only if they looked.
- **The Sharpie hand**: dil_stash, then idle_spares, then a late note (sharpie2,
  days 26–39) that fires only if the stash was found earlier.
- **The delay**: a live call (early), comm_delay (middle), a late video message
  that arrives after the event it was about.

## Characters

All seven are competent, kind, and tired in different ways. Traits (brave,
curious, warm) choose which option fires and who gets cast. Skill flavor stays
subtle: Diego's eye for parts and fits, everyone else's for loops, logic and
sensors. Never name the job, and use it in no more than about 1 card in 6.

## Cliffhangers

The hooks in 70_hooks.lv follow the STYLE.md rules. The new hooks lean toward
the uncanny over repairs:

- a voice on the loop at night;
- a ship that drops off the net.

Both resolve in grounded ways that leave a residue: one tender, one unsettling.

## Reserved words

engagement keeps `content/engage/reserved.json`: story words that engagement/UI
text must not use. That file lives on the engagement branch only, so this list is
the source to sync from. "Cargo 2" stays as the story's name (the gifts label's
everyday "cargo" should change there, not here).

Cargo 2, smudge, streak, shadow (of a ship), fingers crossed, self-test,
safe-mode, pixel, night frame, fast sequence, spin, turns a minute, between
boots, old channel, retired channel, aim for the light, eleven / 11 seconds,
Sharpie, you'll thank me, written off, lost on landing, landing lights.

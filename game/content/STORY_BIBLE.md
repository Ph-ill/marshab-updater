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

1. **Leaving (days 1–10).** Earth fills the window. Calls home are still live
   conversations. The ship is new, and the crew is still learning its noises.
   Plant everything here.
2. **The middle dark (days 11–28).** Earth becomes a dot. Calls turn into
   letters. The routine hardens into rituals, the isolation bites, and the
   carrier and the flare nights come. The garden fails here.
3. **The approach (days 29–38).** Mars becomes a disc, then a place. The things
   earlier missions left behind start to answer. There's one big fleet choice
   about arrival.
4. **Arrival (days 39–42).** Everything planted pays off, and one of the
   endings closes the log.

## The ramp (slow burn)

| Phase | Mystery content |
|---|---|
| 1 (days 1–10) | None. Only plants that read as ordinary life: the thumb, the Sharpie, the garden, the live call. |
| 2 (days 11–24) | The carrier vote, which reads as a retired probe's beacon. The noise-floor ripple, which reads as a wheel harmonic. Eleven sparks behind closed eyes (filed as `grim`, not mystery). Each detail has an ordinary explanation. |
| 3 (days 25–36) | The carrier comes back. The uncanny hooks open up (band, ghost, voice, dark). The flashes, first and second sighting, and the vote on them. The crew stops being able to call it chance. |
| 4 (days 37–42) | The overlay (carrier and flash in the same frame). The flash answer, if they looked. The endings. |

## Motifs

| Motif | Planted | Turns | Pays off |
|---|---|---|---|
| **The thumb**: holding a thumb up to a world | The early watch: Earth won't fit behind a thumb | The middle watch: a thumbnail covers Earth | Approach: Mars no longer fits behind it |
| **Eleven seconds** | The carrier repeats every 11 s | Night-side flashes (mystery thread) | See *The lighthouse* |
| **The Sharpie hand**: someone at Starbase packing a margin | The ration stash ("you'll thank me") | A spare that isn't on the manifest | A second note in the same hand, at the moment it's needed most |
| **What earlier missions left** | The safe-mode beacon hook, the spent stage ghost | The carrier | Arrival: Mars orbit is crowded with patient dead machines, and the fleet is the first to come back for them |
| **The delay** | A live call home, with laughter landing in real time | Letters, then monologues | A message that arrives after the moment it was about |
| **The garden** | Seeds planted in the first week | Nothing grows, and the crew keeps watering it anyway | One shoot on the approach, carried down |
| **The shelter between the water tanks** | Flare drills, a deck of cards | Flare nights, shoulder to shoulder | Water is shielding, water is life, water is the last thing checked before landing |

## The lighthouse (main mystery)

The carrier on the old deep-space frequency comes from a dead Mars orbiter. Its
attitude control failed years ago, and it has been tumbling ever since with an
11-second rotation. Its beacon antenna sweeps past the fleet once per turn, so
the signal "repeats every 11 seconds". Its solar panel flashes the same way:
those are the night-side glints in the flash thread, seen against the dark
limb. The reader can solve it before the crew does, by noticing that the two
periods match.

Nothing is ever said outright. The fleet's choices decide how it reads:

- **Answer it** (dec_signal: open). The tumbling orbiter answers between sweeps.
  The fleet has woken an old friend. Ending: *Old Friend*.
- **Log it** (dec_signal: log). The carrier keeps showing up, stronger each
  time, as the fleet closes on the orbit it shares. It reads as being followed.
  Ending: *Company*. Ominous, but accurate: it's just orbital mechanics.
- **The flash thread** (dec_flash). Looking closer resolves the flashes as a
  tumbling panel, without naming it. A reader who remembers the 11 seconds will
  join the dots. Leaving it alone keeps the flashes uncanny.
  - It never contradicts the carrier outcome.
  - It doesn't pick an ending. It adds a line of meaning, and the endings stay
    readable either way.

## Endings (checked in order on day 42)

1. **Old Friend**: the carrier was answered and supplies held.
2. **Company**: the carrier was logged and heard again.
3. **Patience**: the long orbit, waiting out the dust storm.
4. **Through the Dust**: the fleet held the plan into the storm.
5. **The Long Way Round**: none of the above. A quiet, human voyage.

The arrival vote doesn't always open, so a season that didn't chase the carrier
and wasn't hit by the storm reaches ending 5. That should be a real share of
seasons.

## Threads

- **The garden**: a planting beat (first week), a failing beat (the middle
  dark), then one sprout (approach), only if someone kept watering it (the
  `garden` var).
- **The flashes**: the first sighting on the approach; a second sighting at the
  same longitude a few days later; then a fleet vote (look closer / leave it
  for the ground); then a resolution only if they looked.
- **The Sharpie hand**: dil_stash, then idle_spares, then a late note (sharpie2)
  that fires only if the stash was found earlier.
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

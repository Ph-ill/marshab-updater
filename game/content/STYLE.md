# The Long Voyage: card style guide

The players are seven real coworkers. The story is about their astronauts. Write
every card so that the person it lands on would be glad to read it aloud at work.

## The voice in one line

Real Starships, real hazards, real stakes. Space doesn't care, the reports are
cold, and the crew are good at their jobs. The humor is dry, and it's there for
relief.

The bar is literary. Use specific, sensory, economical images (the Sharpie, the
thumbnail held up to the window), never "the vastness of space". Motifs come
back changed. Details planted early pay off late. Keep dread and wonder in equal
measure. Keep the uncanny grounded, and never explain it away cheaply. The
people are competent and kind under pressure. The arc, the motifs and the
plants are in `STORY_BIBLE.md` (spoilers: writers only, and never quote it to
players).

## Setting: grounded near future

- Real SpaceX Starships flying to Mars. Seven ships, **each astronaut belongs to
  a home ship; a ship may briefly hold 0 or 2.** Crossings happen only in a
  transfer window (every fifth day from day 7: a tethered line between hatches,
  paid for in propellant) or an unscheduled rescue window, and an empty ship
  flies itself. Most two-person scenes happen over the fleet link, video, or an
  EVA between ships; an in-person scene needs `when same A B` and reads as a
  visit. Check every `{A}`/`{B}` card for "next to", "hands {B}", "across the
  table" and the like.
- **Days 1–5 are in Earth orbit** (fuelling, tanker dockings, checkouts). Earth
  is huge in the window and calls are live. The departure burn is day 6; any
  card about Earth shrinking, the delay growing, or "since leaving" needs
  `days` starting at 6 or later, and any card about Earth filling the window
  must end by day 5 (low orbit) or day 10 (receding).
- Use real, **public** hazards and hardware: header tanks, methane and LOX
  boil-off, propellant margins, correction burns, the arrival corridor, CO₂
  scrubbers, water recovery, dosimeters, the storm shelter between the water
  tanks, solar particle events, micrometeoroids, EVAs, tethers, star trackers,
  the high-gain antenna, Starbase, Mission Control, anomaly reports.
- Distance is the antagonist. One-way light time: seconds in Earth orbit, about
  a minute by the middle dark (days 17–22), a few minutes on the approach (about
  4 at day 28, 6 at days 33–36), about ten at arrival. Never more than 12
  minutes each way in this season. Earth shrinks to a dot you can cover with a
  thumbnail.
- Arrival is direct entry from the crossing (day 42), or aerocapture into a long
  orbit if the fleet votes to wait. In dust the cameras go blind; the radar
  still has the ground. No reaction wheels on a Starship: attitude is thrusters.
- **Nothing internal or proprietary.** If you only know it from work, it doesn't
  go in a card. No part numbers, no internal tool names, no program names.
- No aliens, no magic, no killer AI. Mysteries resolve into something real: an
  old spacecraft, physics, a failing part, a ground station down in a storm.
- **Time:** the season is 42 flight days. One flight day in the log is about
  five days of real flight, so write "flight day", "this week", "a few days
  later", "since Starbase". Don't write "month three" or "halfway through
  the sixth month". Hours and minutes inside a scene are fine.

## Tone: thrilling first, deadpan second

- Every few days something should make a player's stomach drop: a pressure
  trend going the wrong way, an alarm at 02:00, a crack where there shouldn't
  be one. Give it real stakes: air, water, propellant, dose, a wrist that won't
  bend.
- Then let a competent person handle it. The relief and the humor come after.
- Grimdark, kept grounded (think Dune, The Expanse, a little 40k): the universe
  is indifferent, the cost is real, and the paperwork goes on regardless. "The
  post-flight report runs 4,000 words on propellant margins and doesn't say
  what the trip cost."
- Humor is dry and deadpan, like engineers talking: understatement, procedure,
  permanent marker, "concur".

## The one hard rule: a crewmate is never the joke

- Trouble comes from **space, hardware, or bureaucracy**. It never comes from a
  crew member being careless, lazy, slow or wrong.
- When two people disagree, both positions are reasonable, and whoever "loses"
  is gracious, or turns out to have had a point.
- When something breaks, someone notices it early, fixes it well, and looks
  after the others.
- Cards bind roles at random, so any line can land on any of the seven. Read
  each line once with every name in it. If it would sting for anyone, rewrite it.
- Teasing aims at objects: the coffee maker, the scrubber, the bracket, the
  form. "Labelled 'temperamental' in permanent marker" is fine. "Jai forgot
  the seals again" is not.
- No gendered pronouns: the compiler rejects he, she, him, her and the rest. Use
  the name ({A}, {B}) or "they".

## Subtle skill flavor

Six of the crew are controls and automation engineers, and Diego is a mechanical
design engineer. Some situations should feel familiar to them **without ever
saying so**.

- Never name-check it: no "as a controls engineer...", no "Diego, the
  mechanical one". No jargon dumps. One familiar detail per card, at most.
- The card should still make sense to someone who isn't an engineer.
- Controls ideas: a loop that hunts after someone touches the gains; two sensors
  that disagree and need a third vote; an interlock that is technically right and
  very inconvenient; an alarm flood with one real alarm buried in it; stale data
  that looks live; putting something in manual "just for a minute"; a watchdog
  rebooting a box all night; a deadband argument; overshoot.
- Mechanical ideas: a bracket that was fine in the model and not fine as built;
  a tolerance stack; a torque value nobody wrote down; thermal expansion; a part
  redesigned with zip ties and spite; a margin that was "plenty" on paper.
- Most cards cast anyone, so put controls flavor on general cards.
- For mechanical cards that should *lean* toward Diego, use a twin: an untagged
  card plus a copy with `when tag A mech`, each with `when !fired <other>`. That
  way Diego gets it more often, but anyone can. Never lock a storyline to one
  person, and don't make every Diego card mechanical.
- Keep it rare: roughly 1 card in 6 to 8. Mark those cards `cat <category> skill`.
  The lint fails above 18%.

## The slow burn

The uncanny ramps up over the voyage. Prefer understatement to announcement:
let the reader notice, and never tell them a thing is mysterious.

| Days | What's allowed |
|---|---|
| 1–10 | Nearly nothing odd. This stretch is wonder, people and ship life. Any oddity is tiny, deniable and easy to miss. No spooky framing at all: no "eerie", "impossible", "strange", "wrong", "chill", "nobody says why". |
| 11–24 | A few small details a careful reader could connect. Each one has an ordinary explanation on the page. Most of what happens is still real-world drama. |
| 25–36 | The crew can't deny the pattern any more. Tension and dread rise, and the cliffhangers lean on it. |
| 37–42 | The payoff. |

- Early cliffhangers are grounded: mission stakes and human stakes. An uncanny
  hook (`cat mystery`) starts on day 25 or later.
- The lint (`check_ramp` in lvc) warns if:
  - a card that can fire before day 11 uses spooky vocabulary;
  - a card that can fire before day 11 is `cat mystery`;
  - a mystery cliffhanger can fire before day 25.

## Content mix

This is a voyage, not a maintenance log. Every card carries `cat <category>`
after its `type` line:

| cat | What it's for | Target share |
|---|---|---|
| `wonder` | Deep-space sights: Venus casting shadows, comet tails, Mars becoming a disc | 8–15% |
| `mystery` | Eerie signals and unexplained things, kept grounded; threads that cross the voyage | 10–15% |
| `human` | Home, letters, the growing delay, music, dreams, grief, quiet friendship | 15–20% |
| `life` | Ship life and rituals: meals, games, birthdays, the garden, movie night | 12–18% |
| `mission` | Fleet choices about the mission: science, names, milestones, course | 6–10% |
| `arrival` | The approach and arrival | 4–8% |
| `grim` | Isolation, radiation, risk, bad news with a delay | 10–15% |
| `repair` | Hardware faults and fixes | **at most 25%** (aim for about 20%) |
| `ending` | The endings | n/a |

- Repairs are spice. When a fault card is needed, make it about the people
  (who wakes up, who brings the spare), not the procedure.
- The crew should spend more of the voyage looking out of the window than
  into an access panel.
- `lvc` prints the mix on every build. It warns (and the tests fail) if repairs
  go above 25%, skill flavor goes above 18%, or a card has no `cat`.

## Cliffhangers

- A `hook` card is the last line of its flight day: an unresolved moment that
  brings people back tomorrow. "At 23:40 the dish picks up something on the
  emergency band. It's not from Earth."
- The engine spaces hooks at least 4 days apart (about one every 5 days), so they
  never run two days in a row, and never fall in the last two days.
- Every hook needs a resolver: a `due once` event with `when fired <hook>`, which
  fires first thing the next day. Bind the same astronaut with
  `do who hook_who A` on the hook and `when is A hook_who` on the resolver.
  (All hooks share `hook_who`, which is safe because they never overlap.)
- Resolutions are **mostly satisfying, sometimes ominous, never cheap**. "It was
  nothing" is banned. The answer is real and specific, and someone did something
  good to find it. An ominous resolution still explains the mystery. What's
  ominous is what it means.
- Write the hook in the present tense, with a clock time and one concrete
  detail. Stop at the worst moment. The resolver opens with what happened
  overnight.
- text.json marks hook cards with `"h":1`, so the phone can show the line as
  "Last night...".
- `clue` marks a fair-play clue (STORY_BIBLE.md has the list). text.json
  collects them in `"reread"`; the end screen lists their flight days with no
  explanation. A clue card must read as ordinary on first pass.

## Repetition caps and the climax

- A beat that would read as a tic if it came back: `once`. Recurring scenes
  (shelter nights, galley, gym, letters, idle watches): `cooldown 18` or more.
- No stock gestures: nobody "reads it twice", "goes to make coffee" or "doesn't
  say anything for a while" more than once in the whole deck. Grep before you
  commit.
- Days 40–42 are quiet: only arrival cards, `reveal` cards and endings. Hooks
  end by day 36, their resolvers by day 37, everything else by day 39.
  `test_climax_is_clear` enforces it.
- Endings are checked in deck order on day 42. Combine every big choice into
  the endings rather than letting an earlier ending hide a later vote.

## Clue keywords

- `clue`: a fair-play clue; listed in text.json `reread`.
- `clue core`: a clue every season must deliver before the reveal. Make it a
  `due` card with a tight window; if it needs a decision, open the decision from
  a due event with `do open <card>`. `sim/season.py --seasons 300` exits 1 if a
  season misses one.
- `reveal`: the payoff card(s); the fair-play check runs up to the first one.
- Simulator output is spoiler-free by default (no ending ids, no card text);
  pass `--spoilers` to see them.

## Card types and what they're for

| type | use it for | notes |
|---|---|---|
| decision | fleet votes with two reasonable sides | Set a flag per option and pay it off weeks later with a `due` callback. |
| dilemma | a private choice for one player's astronaut | Both options are decent people doing decent things. The cost is the interesting part. |
| rescue | someone needs help from another ship | One tap is enough. The default must also be fine. |
| event | something happens to the fleet or a ship | Can auto-pick an option from a trait (`lean`). |
| beat | small human moments between crew | Most of the log. Keep them warm. |
| hook | the cliffhanger at the end of a day | See above. |
| ending | the arrival | Checked in order. The last one has no conditions. |

Idle-friendly beats (`when idle A >= 3`) are for astronauts whose players haven't
been in for a while. They must make the absent person look good: quiet
competence, kindness, the extra watch nobody asked for.

## Length

- Card text: 1 to 3 sentences, under about 300 characters (payoff cards, from
  day 40, reveals and endings, may run to 420). Phone screen, captive
  sheet.
- Button labels: 2 to 5 words.
- Outcomes: 1 to 3 sentences. End on the image or the joke, not on a moral.

## Examples

Good:

> Behind a stowage panel, Jai finds three ration packs that never made the
> manifest. Someone at Starbase wrote "you'll thank me" on the bag in Sharpie.

> Dorian runs the dosimeter check. The fleet has taken the radiation of a few
> dozen chest X-rays so far. Dorian writes it down, underlines it, and goes to
> make coffee.

> A solar flare is 40 minutes out. Every crew packs into the storm shelter
> between the water tanks. It's cramped and loud, and Michelle has brought cards.

> Two header tank sensors agree; the third doesn't. Kim pulls the raw data: the
> two that agree share a power supply that's sagging. *(controls, subtle)*

> Every part is in tolerance. Stacked together, they're 1.4 millimeters out.
> *(mechanical, subtle)*

Bad, and why:

- "Diego forgets to torque the bolts and the panel flies off." A crewmate is the
  cause and the joke.
- "As a controls engineer, Kim retunes the PID loop's integral term." It
  name-checks the skill and dumps jargon.
- "The signal was just a glitch. Nothing happened." It's a cheap resolution.
- "An alien probe locks onto the fleet." It isn't grounded.
- "By month four the crew are exhausted." It pins down calendar time.
- "Jai spends the whole shift on the toilet." It mocks a person, not an object.

## Before you commit

1. `python3 tools/lvc.py`: it must compile with no pronoun errors and no
   `style:` warnings. The lint flags hard-coded crew names, name-checked jobs,
   words that make someone the joke, cheap resolutions, calendar pins, and
   over-long text. It also flags a repair share above 25%, skill flavor above
   18%, or a card without `cat`. It's a safety net, not a substitute for
   reading the lines.
2. `python3 sim/season.py` and read `sim/out/narrative.txt` with real names in
   it. Ask, for every line: would this person be glad to read it?
3. `sh tests/run.sh`: all 7 ships must produce identical digests.

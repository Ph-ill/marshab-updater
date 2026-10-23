# The Long Voyage: card style guide

The players are eight real coworkers. The story is about their astronauts. Write
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

- Real SpaceX Starships flying to Mars. Eight ships, **each astronaut belongs to
  a home ship; a ship may briefly hold 0 or 2.** Crossings happen only in a
  crossing window (every fifth day from day 7: a tethered line between hatches,
  paid for in propellant) or an unscheduled rescue window, and an empty ship
  flies itself. No crossing out after day 32, everyone home from day 37, none
  on days 40–42. A card set on an ordinary day says "the last/next transfer
  window", never a crossing that day. Most two-person scenes happen over the fleet link, video, or an
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
- Distance is the antagonist. One-way light time to Earth (engineer's table,
  2033-05-08 departure, cross-checked by the round 15 engineer's model):
  seconds in Earth orbit, 1.5-2 minutes by days 19-21 (93-116 s, round 16 engineer), about 3 at day 25, 5 at
  day 33, about 7.5 at day 40 (452.7 s; round trip "a quarter of an hour", round 18
  engineer), 8 at arrival (day 42); the round trip on sol 2 is 16.7 minutes, so a
  surface waiver takes longer than that ("eighteen minutes"). Mars one-way: ~100 s at day 22 (round trip 18 ticks), about 40 s at
  day 34 (39-42 s, round 20 engineer), about thirty seconds at day 36 and a second less each day (33.1-29.4 s over
  log day 36, DE440s; `m_overlay` says "thirty seconds now, a second less each day"), 15 s at day 39, 10 s round trip
  at day 41 (5 s one-way). The carrier slides against fleet time by about 1.65
  seconds a day around day 20, easing to about one second a day from day 28 to
  41 (DE440s, round 18 engineer). The tick is 10.96 s; in prose say "about eleven
  seconds", never a rounder or sharper figure. Storm dose: "past a hundred millisieverts" on days 20-21, never a sharper figure (the round 17 model gives 72-101 mSv over that stretch, MSL/RAD rates give 120-140; "past a hundred" holds under both, round 20 engineer); never earlier. Write the shrinking numbers, never a fixed one. Never more than 9 minutes each way in this
  season. Earth shrinks to a dot you can cover with a thumbnail.
- **Approach timeline.** Day 36–37: about twenty-five light-seconds out. Day 38:
  Mars "under three weeks out" in real flight. Day 41: inside five
  light-seconds (Mars about half lit, phase near 92°, the dawn line almost straight down the middle; round 17), about five days before atmospheric entry (a 10 s round trip is 1.5 million km, 5.0 days out at 3.45 km/s; write "five days out", round 20 engineer) ("the last night
  before entry" belongs to day 41). Day 42: entry morning. Plasma blackout is "three minutes" (under four for a Mars entry), the same on every entry card. Venus casts a hand shadow only in the first ten days (`w_venus_shadow` days 7-10). Round trip to Earth at day 19 is about 3 minutes (2.9-3.1, round 20 engineer). Arrival is direct
  entry from the crossing, or aerocapture into a long orbit if the fleet votes
  to wait.
- **EVAs are never solo.** A partner is suited at the next ship's hatch, or the
  card says the EVA was scheduled with one. An unscheduled EVA costs a closed-up
  window and propellant. Crossing the transfer line means a morning of
  prebreathe on oxygen first. In dust the cameras go blind; the radar
  still has the ground. No reaction wheels on a Starship: attitude is thrusters.
- **Nothing internal or proprietary.** If you only know it from work, it doesn't
  go in a card. No part numbers, no internal tool names, no program names.
- No aliens, no magic, no killer AI. Mysteries resolve into something real: an
  old spacecraft, physics, a failing part, a ground station down in a storm.
- **Time:** the season is 42 flight days. One flight day in the log is about
  five days of real flight (one log page), so write "this week", "a few days
  later", "by the next log page". Don't write "month three" or "halfway through
  the sixth month". Hours and minutes inside a scene are fine. Counts that
  span pages (knocks, hellos) are real-day counts; say the span in days ("a
  hundred and twenty days back") so a numerate reader doesn't divide by
  pages. Until the web header shows the page convention (see the bible's web
  hand-off note), avoid "in N days" that lands inside one page.
- **Page headings (round 19).** The log prints each page as `LOG PAGE NN · DAY n`
  for pages 1–6 (one day each, Earth orbit) and `LOG PAGE NN · DAYS a–b` from
  page 7, where a = 7 + 5·(NN − 7) and b = a + 4 (`sim/render.py`
  `page_heading`, mirrored in `tests/render_check.mjs`). Write so a scene sits
  inside its page's span; "by the next page" means about five days.

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
- Grim, round 19: let the cost land on an object, a form or a number, never on
  a crewmate's body for a laugh. The shelter deals cards while next-of-kin
  forms come up for re-signing; the medical kit has a line item called
  "contingency, crew, 1". State it once, flatly, and move on: no adjectives,
  no dwelling, and nothing uncanny before day 11.
- Humor is dry and deadpan, like engineers talking: understatement, procedure,
  permanent marker, "concur".

## The one hard rule: a crewmate is never the joke

- Trouble comes from **space, hardware, or bureaucracy**. It never comes from a
  crew member being careless, lazy, slow or wrong.
- When two people disagree, both positions are reasonable, and whoever "loses"
  is gracious, or turns out to have had a point.
- When something breaks, someone notices it early, fixes it well, and looks
  after the others.
- Cards bind roles at random, so any line can land on any of the eight. Read
  each line once with every name in it. If it would sting for anyone, rewrite it.
- Teasing aims at objects: the coffee maker, the scrubber, the bracket, the
  form. "Labelled 'temperamental' in permanent marker" is fine. "Jai forgot
  the seals again" is not.
- No gendered pronouns: the compiler rejects he, she, him, her and the rest. Use
  the name ({A}, {B}) or "they".

## Subtle skill flavor

Seven of the crew are controls and automation engineers, and Diego is a mechanical
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
  fires first thing the next day. Resolvers live in `cards/05_resolvers.lv`, which
  sorts first, so they lead the day's due cards (after decision closings). Bind the same astronaut with
  `do who hook_who A` on the hook and `when is A hook_who` on the resolver.
  (All hooks share `hook_who`, which is safe because they never overlap.)
- Resolutions are **mostly satisfying, sometimes ominous, never cheap**. "It was
  nothing" is banned. The answer is real and specific, and someone did something
  good to find it. An ominous resolution still explains the mystery. What's
  ominous is what it means.
- Write the hook in the present tense, with a clock time and one concrete
  detail. (The hook has the clock time; its resolver fires five days later and
  must not give exact clock times for that night.) Stop at the worst moment. The resolver opens with what happened
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
- Round 18 rules. Endings are present-tense scenes under "From the log:"; only
  backstory takes the past tense. Day 40 ends on the meaning (`a_report` is its
  last card). Rationing is per ship (the others trim to send water). A crossing
  happens in a transfer window (days 7, 12, ... 32) after a morning of
  prebreathe, or in a rescue. No line may lean on a random beat before it fires
  (the galley bread). An injured astronaut is never cast in a haircut or an EVA.
  UI lines with a count must read right at one, or carry no number.
- Endings are checked in deck order on day 42. Combine every big choice into
  the endings rather than letting an earlier ending hide a later vote.
- Retired tics (round 4): "nobody" as a beat ("Nobody laughs", "nobody
  asked"), taping or pinning things to walls, "the channel goes quiet" and
  other hush endings. One of each in the whole deck at most; prefer an action.
- The climax happens on the page: day 42 has an entry scene per arrival branch
  (`e_entry_*`), cast to whoever was drilled on taking the landing by hand (manual takeover, engine-out call, corridor correction; never "manual abort"), and each
  ending is a landing scene, not a summary. Every branch shows the event
  recorder (`a_log` when answered; the unanswered endings otherwise).
- Voices belong to arcs, not people (casting is random). The one exception is
  the per-person quirk lines (see "The habit slot"). See STORY_BIBLE.md
  "Voices". Keep the register different per arc:
  - list: a talker; run-on sentences, lists inside lines ("Hi, it's me, ship's fine, I'm fine, the bread's improving, here's the list");
  - song: taciturn and musical; two-word lines, never explains;
  - garden: chats to the plants; logs failure hopefully;
  - letter: formal and procedural ("Item located."), except about the letter;
  - dose: blunt; argues with numbers, thanks grudgingly ("Fair.");
  - hail: timestamps and radio-terse ("No misses. Patient. Out.", "Booked again. Out.", "Counter noted. Out.");
  - theory: visual; asks questions and draws them, without naming the source or its clock before day 38 (round 19: no "Mars time" or "strobe" in the theory cards);
  - every arc speaks at least once in its own register; never name the skill behind a line, and never make the line about a crewmate's competence (round 17).
  - roles outside the arcs keep a habit too (round 18): the pixel finder (`flash_who`) plots things and puts the pen down; the gust pilot (`abort_who`) flies it once in the sim first; the one who argued to wait (`wait_who`) logs it. Habits, never name-checks.
- Humor lands on the situation, the object or the procedure, never on the
  crewmate's memory or competence (a book written for windowsills, step
  fourteen of a ground procedure, numbers that turned out better).
- Resolvers lead with the struggle and land on the outcome ("Fourteen minutes of
  the control loop fighting a roll..."), never "{A} fixed it by morning:" first
  (round 17).
- Anomaly dismissals vary: an action, a crew line, a filing place, a one-word
  hedge ("Probably."). Never the same "moves on to..." tag twice.
- Retired tics (round 5): "since Starbase", "slowly", "Around the fleet" and
  other filler fold lines (fold lines name a concrete chore), "nobody" anywhere
  in card or system text.
- Retired tics (round 6): "Neither of them…" endings, "doesn't mention",
  "reads it twice", "Slowly." (give a rate), pinning things above bunks (clip
  them inside the logbook). Night scares stay grounded: no "by itself", no
  "it has moved"; give the hardware a cause.
- Retired tics (round 8): "taped", "pinned up", "the galley wall", "go quiet"
  and its forms. "Five days" appears once per season in the closing cards, not on
  every descent beat.
- The retired-tic list is enforced by `test_retired_tics_stay_retired`
  (tests/test_content.py); add to its list when a tic is retired.
- One seat a ship: critical commands are read back by the next ship (planted in
  `l_transfer`). Overrides and one-off commands say who read them back. Crew
  "votes" on trajectory are recommendations the flight director takes.
- Light-time numbers follow the table above on the card's fixed day; check
  any new number against it (one closing rate, everywhere).
- Fold lines: none on the final day, printed before a hook, never naming
  anyone who had a scene that day.
- Epilogue: every astronaut gets a line. Story lines first; fallbacks from
  `epi.axis` / `epi.bond` / `epi.plain` (sim `Renderer.epilogue(out, st)`).
- Round 20 rules. Tie closes come from the `sys.dec_tie` pool (a list in
  system.json; both renderers step through it in order, one counter per pass over the story), and say "{n} ballots", never
  "votes". A decision outcome never restates who decided: the lead line already
  did. Habit lines don't share openers ("Every data drop", "Last mail before
  entry" are retired, and linted); a habit never touches ship systems for a joke;
  one hobby shows at most twice per crewmate a season, and two crewmates never
  share a hobby costume. Ending sign-offs land on Cargo 2's character (stubborn,
  slow, generous), not on a pun, and every number a reader can check (dose,
  light time, battery) follows the table above. The middle (days 17-27) keeps one
  quiet grim line item in play (`g_margin`, `g_count`): a form, never a speech.

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
  day 40, and reveals may run to 420; endings to 640, lint MAX_ENDING, because
  they carry the shared coda). Phone screen, captive sheet.
- Button labels: 2 to 5 words.
- Outcomes: 1 to 3 sentences. End on the image or the joke, not on a moral.

## The habit slot (per-person quirks)

`content/roster.lv` is the quirk table: each astronaut's line carries up to
four `habit "..."` entries (escape inner quotes as `\"`), written with `{A}`
and no other slots. Two card forms use them:

- `each crew` clones a card once per astronaut (`id_1`..`id_N`, each bound to
  that astronaut with a crew mask) and fills `{habit}` with the first habit.
- `each habit N` (round 19) clones only for astronauts who have a real Nth
  habit; the neutral placeholder or a missing entry makes no clone. The
  quirk beats `quirk_1`..`quirk_3` (days 2–6, 23–29, 35–39, `once`, weight 14)
  use this, so each crewmate gets about two to three quirk touches a season and
  each line can only ever render for its owner (tested).

### The voice slot (round 24)

Each roster line may carry one `voice "..."`: that crewmate's own short sign-off,
drawn from their habits (Phill "Saving here.", Jacques "Copy. Done. Next.", Kim
"And scene.", Jai "Clear. Next mark.", Michelle "Story first. Numbers next.",
Diego "Now you: how's your day?", Dorian "Checked. Every line.", Marco
"Capacity: one."). A card writes `{Av}` or `{Bv}` where the role's own
words go, usually a log or radio sign-off, and the renderer fills it with that
crewmate's voice ("Out." if none). A voice prints on at most two cards per
crewmate per season (`VOICE_CARDS` in sim/render.py and web/render.js); later
cards get a plain "Noted.", so write every `{Av}` so "Noted." reads too. Never
hard-code a sign-off like "Out." in a card. The voice follows the person, not the role, so
whoever draws a role still sounds like themselves. lvc measures length caps with
the longest voice. Use it for a closing quote, never as a punchline about the
speaker.

Rules for quirk lines:

- Only facts the player sent in. Never invent a hobby, a family member or a
  view for a real person, and never touch politics, religion or anything a
  crewmate didn't offer.
- Affectionate, light, occasional and subtle: the quirk shows in what the
  person does ("times the coffee to the galley playlist"), not a name-check of
  the hobby, and the joke is never on them.
- No pets, children or partners aboard: the people at home stay at home
  (photos, mail, a drawing on the console).
- Adding a crewmate means adding one roster line with three habits; the clones,
  masks and tests follow automatically.

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
3. `sh tests/run.sh`: all 8 ships must produce identical digests.
- Calendar (round 21): log day d >= 7 covers real days 7+5(d-7) to +4, so day 42
  is real days 182-186. Entry is real day 186, 180 days after the departure burn
  on real day 6; "a 180-day voyage" in the pitch counts from the burn. Light-time
  numbers say what they measure: `m_alias` gives the slide this week (about 1.7 s
  a day at day 20; it shrinks as the fleet closes), `m_overlay` the one-way light
  time from Mars.

# The asteroid duel (0.3.1)

A Battleship-style game between two ships, played over the same ship-to-ship link Hail
uses (board/lvlive.py). Nobody's phone joins another ship's Wi-Fi: each player stays on
their own ship, and each move is one small item carried ship to ship whenever the two ships
meet. A turn can take seconds (ships side by side) or a day (a crewmate away from their
desk); the game doesn't mind.

This file is the design. The code is board/lvduel.py (the rules, the field, the items;
loaded per use), board/lvduelapi.py (what a phone asks for; loaded per request) and
web/duel.js + web/duel.css (the screens).

## 1. The game

* **Field:** 6 x 6 asteroid field, columns A-F, rows 1-6 (36 cells). Small enough to read
  on a phone held in one hand and to answer in one radio item.
* **Fleet:** three ships, 3, 2 and 1 cells long (6 cells), straight lines, across or down,
  never overlapping and never touching end to end or side by side (so a hit next to a
  finished ship is always a miss: fewer wasted shots, shorter games).
* **Hiding:** you place your fleet on your own phone (tap a ship, tap a cell, tap again to
  turn it; or "Shuffle" for a random legal layout). "Lock in" fixes the layout for the
  whole game; it can't be changed after the invitation goes (the ship stores it and
  commits to it, section 3).
* **Turns:** the player who was invited fires first (the inviter already chose the
  moment). One shot per turn, fired from your own ship's page. The other ship answers by
  itself (hit, miss, or "that sinks the 2-cell ship"): the defender doesn't need to have
  their phone out, so the answer can come back in the same link as the shot.
* **Win:** sink all three ships (6 hits). Then both ships reveal their layouts and check
  each other's answers (section 3). The record between each pair of crewmates is kept
  ("3-2 between you").
* **Ending early:** "Resign" (once both ships joined, counts as a loss), "Withdraw
  invitation" (before it's answered, no result), "Decline" an invitation, and "Call it"
  once the other side hasn't moved for 3 days (the game is put away, no result).
  Withdraw and resign are separate phone actions, and the board takes each only in its
  own state: withdraw only while your invitation is unanswered ("wait"; END 3, nothing
  recorded on either ship), resign only in a game both ships joined ("active"). A page
  that still showed "wait" when the ACCEPT landed gets "Your crewmate already joined.
  Resign counts as a loss." and nothing changes; a withdraw never turns into a
  resignation. The withdrawing page says "Invitation withdrawn", the invited page
  "Kim withdrew the invitation" (any END 3 heard while still invited, including the
  inviter's 3-day put-away), and a game put away otherwise says "Duel put away".
  Call it is offered only while you're waiting on the other side in a game both ships
  joined (or its reveal): on your own turn the page doesn't show it, and the board
  answers "It's your move." It isn't offered on an unanswered invitation, because an
  invitation not answered in 3 days is put away anyway. The 3 days are wall-clock time: once a phone has set the clock,
  time a ship spent switched off counts (a gap of 0 to 30 days since the last saved move;
  a clock that jumps backwards never takes idle time away). A move or invitation heard
  while the clock is still unknown (after a boot, before a phone connects) has no known
  wall time: the ship keeps the old saved time but marks it unknown, the page shows no
  "Arrived" age for it, and time switched off after it never counts. Until a phone sets
  the clock and the ship writes an exact time from its own uptime, it counts only uptime
  (saved hourly), so Call it can come late, never early.
* **No result:** either ship can end a game that's still going with no result at any
  time, the same way stalling for 3 days does (a ship that sends END, or simply stops).
  Only resigning a game both ships joined, or a checked reveal, records a result. An
  END 2 (resign) heard for an invitation not yet accepted is a withdrawal: no result.
  A withdrawal or put-away (END 1 or 3) that crosses your accept-then-resign is a mutual
  stand-down: the other ship gave up its own win and sends no REVEAL, so neither ship
  records a result and your page says "Your game ended with both ships standing down.
  No result." instead of waiting on "Checking both fields". Both ships are free for a
  new invitation.
* **Rematch:** "Rematch" (or a new duel with the same crewmate) waits until the last
  duel's END and REVEAL have reached that crewmate's ship: the page says "Your last move
  in that duel is still on its way. Try again after your ships meet." Starting over
  replaces the old game, and dropping its unsent END or REVEAL would leave the other ship
  waiting on it, or one ship counting a result the other never can.
* **Limits:** one game at a time with each crewmate, at most 3 games going at once.

## 2. On the air

Duel moves are Hail items (lvlive.py, "On the air"): 20 bytes each, kind, to, epoch,
seq (2), body (11), mac (4), riding the sync HELLO/DONE trailer, numbered per sender, acked,
de-duplicated and replay-checked exactly like a hail. Nothing about the core sync, the
trailer, the mac or the dial schedule changes. 0.3.0 ships ack and drop kinds above 2, so a
0.3.1 ship's duel items never stick in an older ship's queue.

Kinds (body is 11 bytes; g = game id, 2 bytes, random, chosen by the inviter):

| kind | name    | body |
|------|---------|------|
| 3    | INVITE  | v (1, protocol version, 1 for 0.3.1), g (2), commit (8) |
| 4    | ACCEPT  | v (1), g (2), commit (8) |
| 5    | SHOT    | g (2), n (1, shot number, 1-71, both players' shots counted together), cell (1, 0-35) |
| 6    | ANSWER  | g (2), n (1, the shot answered), cell (1), result (1: 0 miss, 1 hit, 2/3/4 hit and sinks the 1/2/3-cell ship, +8 when that was the last ship) |
| 7    | REVEAL  | g (2), layout (3), salt (6) |
| 8    | END     | g (2), why (1: 1 decline, 2 resign, 3 called, 4 version not supported, 5 busy/too many games, 6 cheat found) |
| 9    | SYNC    | g (2), n (1, the last shot this ship has), last cell (1), last result (1), state (1) |

Implementation clarifications: n must reach 71, not 36: each player can need 36
shots, and the invitee's 36th shot ends the game before the inviter's 36th.
The byte and all other item sizes stay unchanged. Direction is 0 across, 1 down;
the layout packs 7 + 7 + 6 bits followed by four zero bits. Touching means sharing
an edge; diagonal placement is allowed, as the side/end rule above specifies.
SYNC state uses 0 waiting, 1 playing, 2 awaiting an answer, 3 revealing, 4 ended;
bit 7 reports that the duel light is off. This does not reuse the advert's Hail-only
bit. No last shot uses cell/result 255. INVITE/ACCEPT also queue a SYNC to report
the light setting. Crossing invitations keep the lower ship number's invitation.
Lock, invite and accept atomically lock and send; there is no mutable locked draft.
Resignation exchanges reveals before the record is credited, so false answers
cannot be hidden by resigning. Unknown-game SYNC replies are globally limited to
one per hour to keep authenticated junk from filling the shared out-box.

* **Layout (3 bytes):** the 3-ship's first cell (6 bits) and direction (1), the 2-ship's
  first cell and direction, the 1-ship's cell: 20 bits, high bits first, 4 bits zero.
* **Commit (8 bytes):** sha256(b"LVD1" + g + layout + salt)[:8], the salt 6 random bytes
  (os.urandom) made when the layout locks. The commit goes out in INVITE/ACCEPT; the layout
  and salt only in REVEAL, at the end.
* **Versioning:** v in INVITE/ACCEPT. A ship that gets a v it doesn't speak answers
  END why=4 and the page says the crewmate needs to update. Higher kinds (10+) from a later
  release are acked and dropped. A later protocol may add kinds; it keeps these meanings.
* **Ships that can't duel:** Hail's capability bit says a ship reads items, not which
  kinds. A 0.3.0 ship acks an INVITE and never answers, so an invitation acked with no
  ACCEPT/END after the crewmate's ship has been met twice more (or 1 hour) shows "Their ship
  may need 0.3.1"; it's put away after 3 days like any invitation. (If the core's sync
  HELLO carries the firmware version, use that instead and refuse up front.)

### Timeouts, slow and dropped links

* Delivery is Hail's: dial the crewmate while they're near (twice, then once a minute,
  with the shared 20 s gap and backoff), and carry along on any sync either side starts.
  A dropped link just means the item isn't acked yet; it goes again on the next one.
* **Duel items don't expire at the end of the day** (hails do, lvlivein.expire). They
  wait until acked or until their game is put away (3 days idle); a put-away game's END
  still waits to be acked, and a rematch with that crewmate waits for it. The queue shares Hail's
  out-box with its existing size cap; a duel item is never pushed out by hails.
* Idempotent by (g, n): a SHOT or ANSWER with an n already taken is acked and ignored; a
  SHOT out of turn (not the other side's turn by this ship's count) is ignored and
  answered with SYNC.
* **Resync:** whenever a ship sees a move it can't place (unknown g, n skipped, wrong
  turn), or a game has had no move from the other side for 6 hours while it's their turn
  and their ship has been met, it sends SYNC with its own view. The side that is behind
  re-sends its last SHOT/ANSWER (kept in duel.json for exactly this). Moves are
  append-only: a SYNC never rewinds a transcript, never rewrites a stored answer and never
  supplies one of this ship's shots. Only a ship fires its own shots, and only the other
  ship's ANSWER to the shot it's waiting on gives the result. The one repair a SYNC can
  make is that lost ANSWER: the other ship is one move ahead with the cell this ship has
  pending. A SYNC whose last move differs from the move recorded at that number
  contradicts the game both ships committed to: an active game ends there with no result
  (END why=6); a decided or finished game ignores it. A SYNC is never sent more than once
  an hour per game.
* The box file is /data/duel.json (atomic save through lvlivein.save, read back), at
  most 3 games plus the record per crewmate and at most 7 pending rejection
  records (one per other ship). Rejection records retire as soon as their reply
  has been delivered and acknowledged, never before its durable obligation ends.
  The long-history heap fixture includes all seven pending replies and populated
  pair records. Do not treat the former 1.5 KB estimate as a maximum file size.

### Cheating resistance

The game is among friends, but the protocol shouldn't let a modified ship (or a phone
poking the API) win by moving its fleet:
* Layouts are locked and committed (commit above) before the first shot; the other side
  keeps the commit and every answer it was given.
* Answers come from the ship, not the phone, and the API has no way to change a layout
  after lock-in.
* At the end both ships REVEAL; each checks the revealed layout against the commit and
  replays every answer it got against it. Any mismatch: the game ends with no result and
  END why=6 is sent. Nothing is counted before a field checks out, so nothing has to be
  undone. A field that has checked out stays checked: a later REVEAL changes nothing.
* Some answers are impossible on their own: 30 cells are water and 6 are ships, and the
  sixth hit always ends the game. A 31st miss, or a sixth hit without "that sinks the
  last ship", ends the game right away with no result and END why=6, without waiting for
  a reveal a ship answering that way may never send.
* END why=6 is a claim without evidence. A ship that gets one keeps a verified or counted
  result, and a real resignation (either side's) keeps its result. Anything else ends with
  no result, even after the final shot: this ship's own answers prove nothing about the
  other field, and a winner that lied in its answers could send END why=6 instead of its
  REVEAL. A later REVEAL can't revive the game. Nothing is ever subtracted from the record
  and no empty [0, 0] record is left. The END path loads no layout rules.
* The page states a mismatch the same way from both sides, without blaming either: "Your
  ship couldn't check Kim's field. No result." on the ship that found it, and "Kim's
  ship couldn't check your field." (plus "No result." if there's none) on the other.
* A layout that breaks the fleet rules (overlap, touching, off the field) fails the same
  way.
* The 6-byte salt makes guessing the layout from the commit impractical (2^48 x the few
  hundred legal layouts), and the item mac (fleet key) means only the fleet's ships can
  make moves at all. Shot cells are checked on the board (0-35, not already fired).

## 3. The phone

Matches Settings and Hail: the same sections (`.lab` headers), `.row` buttons with the
crewmate portrait, `.btn sec` dock buttons, `.dim`/`.fine` text. No emoji, no gradients,
no new fonts.

1. **Home card** ("Asteroid duel", right label "your move" when one is): up to 3 rows, one
   per game: "Your turn", "Kim's turn", "Kim invited you", "Waiting for Kim to join",
   "Your shot's on its way". Empty: one line of how it works and "Start a duel".
2. **Pick a crewmate**: crewmates' rows (a ship that can't, greyed with the reason).
3. **Hide your fleet**: your 6 x 6 field, the three ships to place, Shuffle, Turn, then
   "Lock in and invite" (or "Lock in and join" when answering an invitation).
4. **Game screen**: their field on top (your shots: hit, miss, sunk outline; tap a cell,
   then "Fire"), your field below, small (their shots on your ships). A line says whose
   turn it is and where the last move stands ("On its way", "Arrived 2 min ago").
   "Resign" sits at the bottom behind a confirm; while your invitation is unanswered it's
   "Withdraw invitation" instead ("Withdraw your invitation? Nothing is recorded."). The
   arrival line shows only while the game is open.
5. **End**: "You sank their fleet in 14 shots" / "Kim sank your fleet"; both fields
   revealed (a game that ended without a checked reveal labels the other field "not
   revealed"); the record; "Rematch".

Words: second person ("Your turn", "You sank..."), crewmates by name, never he/she/they
pronouns in templated text; no story text, no ending names.

## 4. The light

* When a SHOT lands on a ship (its player's turn now), that ship's light flickers: the
  "your move" pattern, two slow pulses (0.6 s on, 0.4 s off) repeated for about 8 s, so it
  reads differently from a hail's 3 Hz. Software PWM through lvflick (lvled's pin), never
  during a link, never in quiet hours, and counted in the same daily allowance as hails.
* Its own switch in Settings, next to "Flicker for hails": **"Flicker for your turn"**,
  on by default (live.json "dl"). Off: the turn shows on the page only, and the
  opponent's page says "Their light is off; they'll see it on their page".
* An INVITE flickers the same way; ANSWER, REVEAL, END and SYNC are quiet.

## 5. Memory

The 32-bit install budget is 110,000 B (owner decision, 2026-10-30), a strict cap: every
gate (tests/mp_sync_heap.py, tests/mp_safe_heap.py, tests/mp_ota_step.py, tools/bench.py)
passes only a peak below 110,000 B, and fails at 110,000 B. The selftest's own 80 KB
check is part of the 0.2.0 firmware (frozen, not shipped by OTA), so it can't change in
this release; tools/bench.py reports the 110,000 B row from the selftest's peak. The gate uses non-collecting operation
probes, not the former post-GC retained-heap figures.
* Resident: the kind dispatch in lvlivein (already loaded per use) passes kinds 3-9 to
  lvduel; nothing new stays loaded between links. Target: under 0.5 KB resident.
* lvduel holds shared state/recovery helpers. Radio rules, phone actions, layout
  validation/scoring and phone snapshots load separately and are dropped after use.
  Recovery runs before the HTTP encoder loads; duel POSTs do not load the Hail API.
* Atomic saves stream JSON through a hashing writer and verify it in 256-byte
  reads before rename. livebox queues encode one entry at a time, without a
  second expanded queue. Transcript iteration does not expand all shots at once.
* GET /api/live keeps a compact private snapshot, counts its encoded length and
  streams the same snapshot in bounded pieces. A radio move between drains
  cannot change that response. No response-sized JSON buffer is retained.
* Probes run inside JSON input reads, serialization writes, save read-back,
  duel storage and view/HTTP construction, without calling gc.collect. The
  normal board allocation threshold bounds uncollected churn independently of
  probes. The gate fails at 110,000 B. The measured duel peak on the 32-bit unix port is
  about 105,500 B (`mp_sync_heap.py --duel --everyone`; the latest figures are in the
  0.3.1 fix reports), so the margin is under 5 KB.
  This simulation does not establish real-Pico fragmentation or BLE heap margin, and no
  real-Pico measurement could be made where these tests run: a Pico W bench run
  (BENCH_TEST.md) is still needed before release.

## 6. Tests

* **game/tests/test_duel.py** (CPython and the MicroPython unix ports, stock and lv32):
  two virtual ships on the fake radio (tests/fakeble) through the real frozen lv/ble.py
  and lv/sync.py: a whole game (invite, accept, alternate shots, answers in the same link,
  last ship, both reveals, commits and answers check out, the record); out-of-turn, a
  repeated cell, off the field; dropped links (the fake radio drops every Nth message) and
  a game still finishing; long gaps (a day between moves: no expiry); SYNC repairs a lost
  ANSWER; a ship that moves its fleet mid-game is caught at the reveal; a broken layout;
  forged SYNCs (a deep rewind, a made-up shot for the other ship, a contradicting move);
  END why=6 after a verified finish, mid-game, while revealing (a lying winner sending it
  instead of its REVEAL records no loss) and after a resignation; a ship answering
  every shot with a miss, or six hits without a sink; days switched off counting toward
  Call it (also after a move heard with the clock unknown, without counting the uptime
  before it), and Call it refused on your own turn;
  decline, resign, call it (not before 3 days), withdraw (refused once the ACCEPT landed,
  resign refused before it), a withdrawal crossing an accept-then-resign (mutual
  stand-down), a rematch waiting for the last REVEAL or END, crossing invitations, too many games, an
  old (0.3.0) ship never answering; v mismatch; the turn light (switch off, quiet hours,
  allowance); fuzz: random duel items never raise.
* **Phone e2e** (web/shots_duel.mjs + shots_duel.sh, Playwright on the fake board): the
  home card, pick, hide (place, turn, shuffle, lock in), fire, the end screen, the Settings
  switch; screenshots for review at 375 px and 320 px, light and dark.
* **Heap** (tests/phone_heap.py --duel, mp_sync_heap.py): a held SHOT travels
  through fake GATT and the real Session._msg during streamed /api/live.
  The critical probe requires an active session, three near-limit transcripts,
  seven pending rejection replies, seven populated pair records and 24 Seen
  receipts still occupying the outbox. The operation peak gates RESULT and the
  process exit status; a cap overrun is never merely printed.
* All existing suites stay green: stock `env -u LV_FROZEN_MP game/tests/run.sh`, lv32
  `game/tests/run.sh`, root `tests/run.sh`.

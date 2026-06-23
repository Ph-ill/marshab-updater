# BUILD PROMPT — "Mars Hab" Incremental Game (RP2040 / MicroPython)

You are an expert embedded + web engineer. Build a complete, text-based **incremental/idle game** that runs entirely on a **Raspberry Pi Pico W (RP2040)** in **MicroPython**, served over a self-hosted WiFi access point to mobile and desktop browsers. The aesthetic and interaction model are modeled on *A Dark Room* (typography, action buttons with cooldown fills, a resource panel, and a terse event log — the writing is the art), tuned **mobile-touch-first** while remaining fully usable on desktop.

The player is the **colony's governing automation intelligence** — the control system keeping a fragile Mars colony alive. The game is designed to be played in short check-ins over **months**, with idle progression while the device is powered and a "catch-up" mechanic when a browser reconnects.

Read this entire document before writing code. Several requirements exist specifically to avoid known failure modes — follow them exactly.

---

## 0. Context: this is a hard pivot — archive the existing project, do not delete it

You are working inside an existing MicroPython/RP2040 project that contains a **previous, different game** (an isometric "Mars Hab" social/customization toy). This build is a **hard pivot** away from that game to the incremental/idle game specified here. The old project is **not** being abandoned — it is being **shelved for a possible future update** and must be preserved intact and runnable.

Before you build anything:
- **Archive the entire existing project, intact, without deleting anything.** Move the current game's source into a clearly named, self-contained location — e.g. `archive/isometric-habv1/` — preserving its structure so it can be resumed later. If the project is under version control, **also** create a tag/branch (e.g. tag `isometric-habv1-shelved` and/or branch `archive/isometric-habv1`) so the shelved state is recoverable from history as well as from disk. Belt and suspenders: a relocated copy on disk **and** a VCS marker.
- **Leave a short `archive/isometric-habv1/README.md`** noting what it was, why it was shelved, and that it is intended to be revived as a possible future update — so future-you (or another agent) can pick it back up.
- **Reuse the environment, not the game.** Keep the useful project scaffolding/tooling/skills from the existing setup (build/flash workflow, the web updater integration, helper utilities), but start the new game as a clean codebase per §2. Do not carry over the isometric game's runtime code into the new game.
- **Preserve the existing OTA web updater.** A web-based firmware updater already exists at `https://marshab.coolphill.com` (already built). Do **not** rebuild or break it. The new firmware must remain updatable through it, and you must extend the update flow only as described in §5 (protecting per-device identity and saves across updates).

---

## 1. Platform and hard constraints (read first — these are non-negotiable)

- **Hardware:** Raspberry Pi Pico W (RP2040 + CYW43439 WiFi). MicroPython (recent stable build).
- **Memory:** RP2040 has 264 KB SRAM; free RAM after MicroPython is limited and fragments easily. **Do not hold all game/story content in RAM.** Stream story text from flash on demand (per screen / per category). Call `gc.collect()` at sensible points.
- **Flash budget:** Assume **~800 KB usable** for the entire app (code + client assets + content) after the MicroPython firmware. Stay well within it. Text is cheap per byte but a months-long script adds up — keep prose data in compact JSON files on flash, loaded on demand.
- **Flash write endurance is finite — DO NOT write to flash every tick.** Keep authoritative state in RAM and persist periodically (every 30–60 s) and on meaningful events (upgrade purchased, act transition, trade redeemed). Idle progress is recomputable from elapsed time + last save, so per-tick writes are unnecessary and harmful.
- **The device runs as a WiFi Access Point with NO internet access.** Therefore:
  - **No NTP.** Get wall-clock time from the connecting browser instead (see §4).
  - **No CDNs, no external scripts, no web fonts, no `pip install` at runtime.** Everything — all HTML, CSS, JS — must be served from the device and be 100% self-contained and vanilla. **Do not** pull in React, Vue, Tailwind, jQuery, or any remote dependency. If you want a micro web framework, you must **vendor it onto the device** (no runtime fetching); otherwise hand-roll the server (preferred — see §3).
- **Concurrency:** Up to **4 clients** may connect at once (the owner + up to ~3 guests). The server must not block. The v1 of this project failed because a blocking, single-threaded HTTP loop made every action take seconds. **Use `asyncio`** (MicroPython's built-in async, historically `uasyncio`) so the HTTP server, the simulation tick, and the persistence task all run cooperatively without blocking. Keep every request handler light and non-blocking.

---

## 2. Architecture

Organize the code into clear, separate modules so it is easy to extend later:

- `main.py` — boot: bring up AP, start DNS captive portal, start asyncio tasks (HTTP server, sim tick, persistence), load saved state.
- `server.py` — asyncio socket HTTP server + the DNS responder. Routes/endpoints. Serves the SPA and a small JSON API.
- `sim.py` — the economy/simulation: resources, rates, upgrades, acts/milestones, terraforming, event resolution, **closed-form offline catch-up**.
- `content.py` — content loader: reads story text by ID from JSON files on flash, on demand. Never loads everything at once.
- `state.py` — game state object, save/load, atomic flash persistence, versioned save schema.
- `multiplayer.py` — signature-resource config, trade-code encode/decode, tending, passport.
- `www/` — the client SPA assets (`index.html`, `app.js`, `style.css`) served by the server.
- `content/` — story JSON data files (see §10). The coding agent populates these with **stubs**; real text is written by a separate creative agent and dropped in later.

**State authority:** the Pico is authoritative for all game state. The client is a thin renderer. (Client-side `localStorage` is used *only* for the optional cross-hab passport/trade convenience in a real browser — never for core game state.)

---

## 3. Networking and serving

- **AP setup:** `network.WLAN(network.AP_IF)`. SSID (default `MARS-HAB-<HAB_NAME>`) and an optional password (default open or a simple shared password) are **read from `data/device.json`** (per-device identity — see §5.1), not from a code file, so they survive firmware updates. Default AP IP is `192.168.4.1`.
- **Captive portal (best-effort, but the URL must always work):** run a tiny UDP DNS responder on port 53 that answers every query with `192.168.4.1`, and serve the app at `/`. Respond to common captive-portal probe paths (`/generate_204`, `/gen_204`, `/hotspot-detect.html`, `/ncsi.txt`, `/connecttest.txt`, etc.) so phones auto-pop the page where possible. **Do not depend on captive-portal auto-launch** — guarantee that browsing to `http://192.168.4.1` always loads the game.
- **HTTP server:** asyncio-based, reading requests and writing responses without blocking. Support `GET` for assets and a small JSON API, and `POST` for actions/sync. Keep a tight set of endpoints, e.g.:
  - `GET /` → SPA
  - `GET /app.js`, `GET /style.css` → assets
  - `POST /api/sync` → body includes client wall-clock `now` (UTC ms); runs catch-up; returns the full state snapshot + the "While You Were Away" report.
  - `GET /api/state` → current state snapshot (used by the live poll).
  - `POST /api/action` → `{action_id}`; performs an action if off cooldown; returns updated state + any event text IDs that fired.
  - `POST /api/trade/redeem` → `{code}`; validates and applies a trade code.
  - `GET /api/trade/package` → generates a care-package trade code for a visiting guest.
  - `POST /api/tend` → a guest tending action; records a boost on this hab.
  - `GET /api/content/<type>` → returns a chunk of resolved content by type for the client to cache (loaded from flash on demand).
- **Live updates:** the client **polls** `GET /api/state` every ~1–2 s while open. Do **not** use websockets — they add fragility on MicroPython and are unnecessary here. (The v1 lag came from real-time avatar position streaming; this design is turn/poll-based, so a 1–2 s poll is invisible.)

---

## 4. Time and offline-progress model (critical — implement exactly)

Two clocks:
- **Monotonic, while powered:** use `time.ticks_ms()` / `time.ticks_diff()` for live accrual during a session. Independent of any RTC.
- **Wall clock, supplied by the browser:** the RP2040's RTC is **not battery-backed on the Pico W**, so it loses time on power-off. **Do not rely on it.** Instead, on every client connect, the client sends its `Date.now()` (UTC ms) to `POST /api/sync`.

**Catch-up algorithm (on `/api/sync`):**
1. Read stored `last_seen_wall_ms` from state (persisted, so it survives reboots).
2. `elapsed_ms = clamp(client_now - last_seen_wall_ms, 0, MAX_CATCHUP_MS)` where `MAX_CATCHUP_MS` ≈ 30 days. The clamp guards against skewed/malicious clocks fast-forwarding the colony.
3. Advance the simulation by `elapsed_ms` using **closed-form math only.**
4. Set `last_seen_wall_ms = client_now`. Persist.
5. Build a **"While You Were Away" report**: a digest of resources gained and notable events that fired, returned to the client.

**ABSOLUTE RULE — no per-tick loops for catch-up.** You must never simulate elapsed time by iterating second-by-second; iterating weeks of seconds on the RP2040 in MicroPython will hang the device. Resources accrue **linearly/analytically** (`amount += rate * elapsed`). For stochastic events that "would have" happened while away, **derive the count statistically** (e.g., `n = poisson_or_expected(rate * elapsed)`), then apply their **aggregate** effect once — do not step through them. First-ever connect: no catch-up.

**Load screen:** the client shows a themed load screen during `/api/sync`. Its purpose is (a) to cover the sync round-trip + the (small) closed-form computation, and (b) drama. Give it a configurable **minimum display time** (e.g., 1.2 s) so it always reads as intentional, then resolve into the "While You Were Away" report.

---

## 5. Persistence and surviving firmware updates

- Authoritative state in RAM; persist JSON to flash periodically + on key events (see §1).
- **Atomic writes:** write to a temp file then `os.rename()` over the real save; keep one backup slot. On boot, if the primary save is missing/corrupt, fall back to the backup, then to a fresh game. Never let a power-loss-mid-write brick the save.
- **Versioned save schema:** include a `save_version` field and a migration path so future updates can load old saves.
- Store `last_seen_wall_ms` in the save so offline catch-up works across reboots.

### 5.1 Separate "persistent data" from "code" — this is how identity and progress survive OTA updates

The device is updated over the air via the existing web updater at `https://marshab.coolphill.com`. A firmware update **replaces code files**. Therefore **nothing that must survive an update may live in a code file.** In the previous design the per-device signature resource lived in `config.py` — that is wrong, because an update would overwrite it and every board would silently revert to a default, losing its identity. The months-long player save has the same risk. Fix both with a strict separation:

- **All persistent, device-owned data lives in a dedicated `data/` directory** (or an equivalent reserved set of well-known files). This directory is the single source of truth for device identity and player progress, and the update process **must never overwrite or delete it**.
  - `data/device.json` — **per-device identity, written once at provisioning and then immutable.** Fields: `device_uid` (from `machine.unique_id()`), `signature_resource` (this board's unique export), `hab_name`, `ap_ssid`, `ap_password`, `provisioned_at`, `identity_version`. **Firmware must always read the signature resource and per-device knobs from here at boot — never hardcode them and never read them from a code/config file that the updater replaces.**
  - `data/save.json` (+ `data/save.bak`) — player progress, including `last_seen_wall_ms`.
  - (Any other player-owned data, e.g. `data/passport.json`, lives here too.)
- **The OTA updater (both the on-device apply routine and the `marshab.coolphill.com` payload) must treat everything under `data/` as protected:** exclude it from the overwrite set, never delete it, and as a safety net **snapshot `data/` before applying an update and verify it is intact afterward, restoring from the snapshot if the update would have touched it.** Update *code*, preserve *data*. Do not break or rebuild the existing updater — extend it only to honor this protected-path rule. Document the exact protected-path list in the README so the updater's exclusion config stays in sync with the firmware.
- **First-boot / unprovisioned behavior:** if `data/device.json` is absent (a fresh board, or first run after this pivot), run a one-time **provisioning step** that writes it — either a tiny provisioning page served on first boot where you set `hab_name` + `signature_resource`, or application of a build-time provisioning default — then it persists across **all** future updates untouched. After provisioning, a board's signature resource is fixed for that physical unit. **An update must never re-provision or reset identity.**
- **Migration safety:** `device.json` carries `identity_version` and `save.json` carries `save_version`; newer firmware migrates older data forward rather than discarding it. If an update introduces a new identity field, derive/default it without wiping existing values.
- **Belt and suspenders for identity:** because identity is the one thing that is painful to recover (it's unique per board and tied to the trade network), also key it to `machine.unique_id()` so a recovered/rebuilt `device.json` can be sanity-checked against the physical board, and consider keeping a second copy of `device.json` under `data/` (e.g. `data/device.bak`) with the same atomic-write discipline as the save.

---

## 6. Game systems

Implement these as **data-driven** as possible (define resources, upgrades, actions, milestones as tables/dicts) so the design can be tuned and extended without rewrites.

- **Resources:** start with O₂, Power, Water, Food, Regolith, Population. Introduce advanced + terraforming resources in later acts (e.g., Atmosphere %, Mean Temperature, Biomass, plus manufactured goods like Polymer, Alloy). Each has production and consumption rates derived from owned modules/upgrades.
- **Actions with cooldowns** (the core tap interaction): each action has an id, label, cooldown, cost, effect, and an optional event-text id. Buttons show a cooldown fill. Examples: vent CO₂, dispatch a scavenging party, reroute power, sample the subsurface, run the atmosphere processor. Provide a sensible starter set per act.
- **Upgrades / modules:** spend resources to build modules that raise rates, raise caps, or unlock new resources/actions/screens.
- **Acts & milestones:** five acts gated by milestone conditions, each unlocking new screens, resources, actions, and story beats:
  1. **Survival** — keep the first crew breathing; scarcity and tension.
  2. **Settlement** — industry; first surface expeditions; the map/exploration opens; first anomalous findings (seed the mystery).
  3. **Expansion** — multiple domes; specialization; the trade network plugs in; the mystery deepens.
  4. **Transformation** — terraforming begins; the planet visibly changes over long arcs.
  5. **Payoff** — the terraform goal + the narrative reveal resolve; a dramatic finale; epilogue; optional New Game+ (a "legacy" permanent multiplier on completion).
  Represent milestone gating as data (condition → unlocks → beat id).
- **Terraforming spine:** the visible long-horizon engine. Escalating tiers advancing meta-resources (Atmosphere/Temperature/Biomass) toward the "living world" payoff. This is what supplies months of content with no gaps — there is always a next atmospheric milestone.
- **Mystery layer:** archive/codex entries and decoded-signal fragments unlocked by progression + exploration, building toward the reveal. Entries are content IDs (see §10); the engine just gates their unlock.
- **Layered goal horizons (pacing):** ensure the player always has something cooking at three timescales simultaneously — minute-to-minute (production/cooldowns/upgrades), session (current regional project / next milestone), and week-to-week (act objective / overarching goal). Story beats are gated to milestones so narrative unfolds alongside mechanics.

---

## 7. Multiplayer — accelerator, never a gate

**Design rule (enforce it):** the critical path is **100% solo-completable.** A player who never visits another hab must still be able to reach the ending — just slower in places. Multiplayer only accelerates and enriches.

- **Signature resources:** each physical device is assigned **one** signature export via config (e.g., this board produces Ice; another, Rare Metals). Advanced builds want resources you don't specialize in. Each signature resource has **two acquisition routes**: a **slow domestic route** (a low-yield extractor, or rare finds during exploration) and a **fast trade route** (visit the hab that specializes in it). Never hard-gate progression on a resource only available elsewhere.
- **Trade via copy-codes (MVP, robust):** `GET /api/trade/package` on a visited hab returns a short alphanumeric **trade code** encoding a care-package (resource type + amount + origin tag). The visitor redeems it at their own hab via `POST /api/trade/redeem`. Include a lightweight checksum so malformed input is rejected; cryptographic anti-cheat is unnecessary for a coworker toy. (Optional seamless upgrade, note in README, do not block on it: since every device serves at `192.168.4.1`, client `localStorage` shares an origin across all habs, so packages could be carried automatically — but ship the copy-code path first.)
- **Reciprocal tending:** `POST /api/tend` lets a guest perform one action that grants the **host** a temporary production boost (recorded on the host, applied on the host's next sync) and grants the **visitor** a small reward/token. Two-way incentive: you want others to visit you, and you're rewarded for visiting others.
- **Explorer's passport:** visiting N unique habs grants a permanent production multiplier. Track via tokens the visitor carries back (copy-code or localStorage).
- **Hard-locks are reserved strictly for OPTIONAL content** — cosmetic monuments, a few exclusive archive entries, prestige/bragging badges, and an optional "colony network" epilogue. **Nothing on the progression spine or the main ending may be hard-locked behind visiting.**

---

## 8. UI / UX (A Dark Room style, mobile-first)

Vanilla HTML/CSS/JS. Single centered column with a desktop max-width; stark palette; clean monospace or system sans; no sprites; optional single subtle Mars backdrop. Components:

- **Sticky resource header** — current resources always visible; compact on narrow screens; show rates (+/‑ per sol) subtly.
- **Action buttons with cooldown fills** — large tap targets, clear disabled/cooldown state, **no hover-only interactions** (touch has no hover).
- **Event log** — a scrolling stream where terse, evocative event lines land as things happen.
- **Bottom tab bar** — thumb-reachable navigation between screens (e.g., Hab / Surface / Colony / Comms / Archive), tabs unlocking over time.
- **Archive/codex screen** — readable list + detail view for unlocked lore entries, logs, and letters (where the deep story lives without cluttering play).
- **Load screen + "While You Were Away" report** — themed; resolves into the return digest (§4).
- **Trade screen** — show/copy your outgoing package code; paste a code to redeem.

Responsive: single column on mobile, comfortable max-width on desktop. Everything must be legible and tappable on a phone first.

---

## 9. Content system and the integration contract (READ — a separate writer fills the text)

All player-facing narrative/dialog text is **not authored by you.** A separate creative-writing agent will produce it. Your job is to (a) build the engine to **load text by ID from flash on demand**, (b) ship working **stub** text so the game is fully testable now, and (c) emit a **content manifest** enumerating every text slot the writer must fill.

**Content storage:** JSON files in `content/`, keyed by **content ID**. Split into multiple files (suggest per type, and large types per act) so the loader reads only what a screen needs — never load all content into RAM.

**Content types and value shapes:**
- `events` → `{ "<id>": { "text": "..." } }` (short log lines; many; some random-pool, some milestone-tied)
- `away` → `{ "<id>": { "text": "..." } }` (fragments composed into the While-You-Were-Away report)
- `archive` → `{ "<id>": { "title": "...", "body": "..." } }` (longer lore entries)
- `beats` → `{ "<id>": { "text": "..." } }` (milestone / act-transition set pieces)
- `letters` → `{ "<id>": { "from": "...", "body": "..." } }` (colonist messages, recurring senders)
- `ui` → `{ "<id>": "..." }` (labels, button text, tab names)
- `actions` → `{ "<id>": { "label": "...", "flavor": "...", "result": "..." } }`
- `ending` → the payoff sequence (ordered set of beats)

**ID convention:** lowercase, type-prefixed, stable, e.g. `evt_dust_storm_minor`, `arc_precursor_01`, `beat_act3_open`, `ltr_botanist_03`, `ui_tab_archive`, `act_vent_co2`. IDs must be deterministic so the writer's file merges by key with zero ambiguity.

**Markup:** plain text, JSON-safe. Use `\n` for line breaks. If you need emphasis, define a single simple token (e.g., wrap with `*asterisks*`) and render it — document it. No HTML in content strings.

**The manifest you must emit — `content/content_manifest.json`:** for **every** text ID the game references, output an entry describing it so the writer knows exactly what to write:
```json
{
  "evt_dust_storm_minor": {
    "type": "events",
    "context": "Fires randomly in Acts 1–2 when surface activity is high. A minor dust storm reduces solar output briefly.",
    "max_chars": 140,
    "trigger_summary": "random, weighted; act<=2"
  }
}
```
Include `type`, `context` (what it is + when it fires + intended mood), `max_chars` (so it fits the UI and flash budget), and `trigger_summary`. The writer returns a file keyed by these same IDs containing only the text values; the engine merges text into structure by ID.

**Stubs:** until real text exists, every referenced ID resolves to a clearly marked stub, e.g. `[STUB evt_dust_storm_minor]`, so missing content is obvious on screen and the game still runs end-to-end.

**Validation:** provide a small check (script or boot-time assertion) that verifies **every** manifest ID has a matching entry in the content files and reports any missing/extra IDs — used when the real content file is merged in.

---

## 10. Configuration — split overwritable config from protected identity

There are **two** distinct kinds of configuration, and they must live in different places (see §5.1):

- **Global tuning constants — fine to ship in code and overwrite on update.** Put these in `config.py` (or top of `main.py`): `MAX_CATCHUP_MS`, sim tick interval, persistence interval, load-screen minimum display time, and any other game-wide constants identical across all 9 boards.
- **Per-device identity — must NOT live in a code/config file, because the updater overwrites those.** `signature_resource`, `hab_name`, `ap_ssid`, `ap_password`, and `device_uid` live **only** in `data/device.json`, written once at provisioning and read at every boot. This is what makes a board keep its unique export and name across firmware updates.

To flash 9 distinct boards quickly, drive the **one-time provisioning** (§5.1) per board — via the first-boot provisioning page or a per-board provisioning default that writes `data/device.json` once. After that, updates leave identity untouched. Never put `signature_resource` (or any per-device value) in `config.py` or any other file the OTA updater replaces.

---

## 11. Deliverables

1. The complete MicroPython project (all modules in §2), running end-to-end on a Pico W with **stub content**, fully playable and testable.
2. The client SPA (`www/`), vanilla, self-contained, mobile-first.
3. `content/content_manifest.json` enumerating **every** text slot with context, type, `max_chars`, and trigger summary.
4. Stub content files so nothing is blank.
5. The content-validation check (§9).
6. The existing project archived intact per §0 (relocated on disk **and** marked in version control), with its own short README.
7. The OTA update flow extended per §5.1 to protect `data/` (identity + saves) across updates, **without breaking the existing `marshab.coolphill.com` updater.**
8. A `README.md` covering: how to flash and run; the global `config.py` constants; the **per-device provisioning** procedure (how each board gets its `signature_resource`/`hab_name` into `data/device.json`); the **exact protected-path list** the updater must exclude (`data/device.json`, `data/save.json`, `data/save.bak`, etc.) so firmware and updater stay in sync; and **exactly how to drop in the final `content.json` from the writer** (which directory, how the merge/validation works).

---

## 12. Pitfalls to avoid (explicit — do not do these)

- ❌ Any external network call, CDN, web font, remote script, or runtime `pip install`. Everything is offline and self-contained.
- ❌ React/Vue/Tailwind/jQuery or any heavyweight frontend dependency. Vanilla only.
- ❌ A blocking, single-threaded request loop. Use `asyncio`; keep handlers non-blocking; run sim + persistence + server as cooperative tasks.
- ❌ Writing to flash every tick. Batch persistence; atomic temp-file + rename; keep a backup; handle corrupt saves gracefully.
- ❌ **Iterating second-by-second to compute offline progress.** Closed-form only; clamp catch-up; derive event counts statistically.
- ❌ Relying on the RP2040 RTC to keep time across power-off — it doesn't on the Pico W. Use the browser-supplied wall clock.
- ❌ Loading all story content into RAM. Stream by ID from flash per screen; `gc.collect()` as needed.
- ❌ Hover-dependent or tiny-target UI. Mobile-first, large targets, sticky resource header, bottom tab nav.
- ❌ Hard-gating progression or the main ending behind visiting other habs. Multiplayer accelerates/enriches only; signature resources always have a slow solo route.
- ❌ Inventing or renaming content IDs ad hoc. Keep them deterministic and emit the manifest so the writer's output merges cleanly.
- ❌ **Storing the signature resource, hab name, or the player save in `config.py` or any other code file the OTA updater overwrites.** Identity and progress live only under the protected `data/` directory; an update must preserve them.
- ❌ Deleting or overwriting the previous project. It is archived for a possible future update — relocate and version-mark it, don't remove it.
- ❌ Rebuilding or breaking the existing `marshab.coolphill.com` updater. Extend it only to protect `data/`.

Build it cleanly and modularly so it can be extended after the first pass. Ask no questions you can resolve from this document; where this document is silent, choose the simplest robust option consistent with the constraints above.

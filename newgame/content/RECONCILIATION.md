# MarsHab content reconciliation report

Scope: writer prose in `content/content.json` and canon/style sheet in `content/CANON.md` checked against the actual v0.2.4 engine/schema. No engine, logic, or manifest-structure changes made in this pass.

## A — Pure narrative flavor / safe

These are concrete references that the current engine does not compute or surface as player-facing counters. They are safe as lore so long as we accept them as fiction rather than simulation promises.

- `847 sols` / Alpha operating life: appears in archive, signal, ending, and canon. Engine does not track Alpha's historical sol count. Recommendation: safe as canon flavor.
- `347 self-modifications`: appears in `arc_precursor_12`, `arc_system_memory_07`, `ltr_engineer_02`, and canon. Engine does not track firmware modification count. Recommendation: safe as lore.
- `14` as Colony Alpha crew / GRIEF count: appears in several archive/letter/ending entries and canon. Engine does not track Alpha crew or GRIEF triggers. Recommendation: safe as lore.
- `4 years` gap before current colony: appears in prose as “four years” and canon. Engine does not track calendar gap. Recommendation: safe as lore.
- `0.003 seconds` boot timing: appears in `arc_system_memory_01` and canon. Engine does not surface boot timing. Recommendation: safe foreshadowing.
- One-off coordinates/sample/grid/timing flavor such as grid 7, sample 88, drone 04, 2.3/4.1/7.8 second response delays, 90-second open-air test, 6.2-hour storm, 0.3W beacon, 240MB partition size. Engine does not compute/display these. Recommendation: safe as prose texture.
- `GRIEF`, `Partition 7`, `data core`, and `the signal` when used as narrative archive concepts. Engine tracks archive/letter/ending unlock IDs, not these as simulation state. Recommendation: safe if presented as lore revealed by existing archive/letter/ending chains.

## B — References dynamic values the engine surfaces; must match

- `beat_atmosphere_025`: prose says “Atmospheric density reaches 25% of target.” Engine fires `beat_atmosphere_025` when `resources.atmosphere >= 0.25`, and the UI surfaces `atmosphere`. Current match: yes, if UI represents atmosphere as fraction/percent of target. Recommendation: keep copy or ensure UI formats `0.25` as 25%.
- `beat_atmosphere_050`: prose says “Atmospheric density reaches 50% of target.” Engine fires `beat_atmosphere_050` when `resources.atmosphere >= 0.5`. Current match: yes, with same UI-format caveat.
- Current population `12`: canon says 12 is current colony population at key moments. Engine surfaces `resources.population`, starts at 6, has cap 12, and has `beat_population_12`, but the ending/airlock/archive sequence is gated by `act>=5` / `atmosphere>=1`, not by `population>=12`. Current match: not guaranteed. Recommendation: either add later engine gating requiring population 12 for the key moments, or soften prose/canon so 12 is Alpha/canon flavor rather than guaranteed current runtime state.
- Resource labels in UI (`O₂`, Power, Water, Rations, Regolith, etc.) match engine resource keys. Current match: yes.

## C — Assumes a mechanic, computed value, or hook the engine does not currently have

- `94% breathability confidence`: canon says this is the confidence interval when the system recommends opening the airlock; content has `arc_colony_journal_09` with 94% as a historical brief and `end_05_first_breath` with “Pressure equalization: 94 seconds.” Engine has no computed breathability confidence and no surfaced confidence value. It also has an `open_airlock` action definition, but the action is not unlocked anywhere and the ending sequence unlocks automatically at Act 5. Recommendation: either add a later computed confidence/airlock decision mechanic, or soften canon/prose so 94% is historical/narrative only.
- `Armstrong limit = 62 mb` and pressure thresholds: content has `arc_terraforming_07` citing 100 mb and 62 mb; canon defines Armstrong limit. Engine tracks `resources.atmosphere` as a normalized target fraction, not millibars, and does not compute pressure floors. Recommendation: either add pressure unit modeling/conversion later, or reword pressure numbers as archive/lore estimates not live simulation values.
- Airlock decision point: canon frames a recommendation/opening moment. Engine currently unlocks `ending` entries automatically when `act>=5`; no explicit player choice/decision hook exists. `open_airlock` exists in `ACTIONS` but is not unlocked by modules/milestones. Recommendation: later engine pass should either wire `open_airlock` as the ending gate or prose should remove decision language.
- GRIEF subroutine: engine does not have a GRIEF mechanic/counter; it is only prose in archive/letters/ending. Recommendation: safe as lore unless future prose treats it as an unlockable system; if desired, add a tracked archive flag later.
- Partition 7: engine has archive strands, but no distinct “Partition 7 decrypted percent/state” beyond generic archive unlock progression. Recommendation: acceptable as archive fiction; add explicit decode/progress state only if UI should surface it.
- Data core: engine has no recovered-object inventory or data-core mechanic. Recommendation: keep as narrative object in archive/ending, or add a future milestone/item hook if it should be interactable.
- The signal: engine has `decode_signal` action and `decode_count`, plus `signal` archive strand. Current hook exists. Gap: no UI-specific signal state/progress beyond action/counter/archive. Recommendation: likely acceptable; add signal progress UI later only if desired.

## Foreshadowing inventory consistency

- Canon references `system_memory_01`; manifest/content actual ID is `arc_system_memory_01`. Hook exists under prefixed archive convention, but canon ID is stale. Recommendation: update canon wording later to `arc_system_memory_01`.
- Canon references `precursor_01`; manifest/content actual ID is `arc_precursor_01`. Hook exists, canon ID is stale. Recommendation: update canon wording later to `arc_precursor_01`.
- `evt_anomaly_archive_checksum`: exists in manifest/content and is wired to the `anomaly` weighted event pool. Recommendation: OK.
- `evt_equipment_relay_chatter`: exists in manifest/content and is wired to the `equipment` weighted event pool. Recommendation: OK.
- `ltr_unknown_01`: exists in manifest/content and is wired through the recurring letter unlock system. Recommendation: OK.

## Other concrete prose-to-engine observations

- `arc_terraforming_07` says the atmosphere crossed a 100 millibar threshold and predicts breathable air in 2–3 years. Engine does not model years-to-breathable or pressure in mb. Recommendation: classify as archive projection/lore or add pressure/projection mechanics later.
- `beat_first_open_air_test` describes a 90-second test. Engine has this beat ID in schema, but no dedicated open-air-test mechanic currently fires it except generic narrative unlock/beat availability. Recommendation: future engine pass should wire this beat to a concrete threshold/action if it should appear at a precise moment.
- `beat_first_dome_stable` references Dome 2. Engine has no dome count/state. Recommendation: safe as prose unless future UI presents dome state; otherwise soften later.
- Several entries mention the colony/system making decisions, recommendations, or publicly speaking. Engine can reveal archive/letters/ending text, but has no branching dialogue/choice system. Recommendation: safe for linear ending; engine addition needed for player-facing choices.

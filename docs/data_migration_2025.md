# Migrating `rules` data from `db_old/` to the new `db/` format

This document is the design/logic reference for re-pointing `apps/rules/management/commands/
import_rules_data.py` (and the models it populates) at the new source dump in `db/`, replacing
the old one now preserved at `db_old/`. Written *before* touching any model or import code, so
the mapping is decided deliberately rather than discovered file-by-file while coding (the same
discipline the README's "Known data-import issues" section calls for on the old format).

`db_old/` has since been deleted from the repo. The one thing still needed from it (Spell class
lists, see below) now lives in `db/spell_classes.json`; the other `db_old/...` mentions in this
document are historical.

## 1. What changed, project-wide

The new dump is a much rawer, closer-to-5etools-source format than the old one (which had
already been cleaned up: synthetic ids, spelled-out enums, a `{meta, items}` wrapper). Every
single `db/*.json` file changed in the same ways:

- **Wrapper key**: `{"meta": ..., "items": [...]}` → a type-named key per entry kind
  (`{"race": [...]}`, `{"spell": [...]}`, `{"itemMastery": [...]}`, etc. — several files now
  bundle *multiple* entry-type arrays in one file, e.g. `db/classes.json` has `class`, `subclass`,
  `classFeature`, `subclassFeature` all at top level). `_load()`'s current
  `json.load(f)["items"]` must become type-aware, not a single generic helper.
- **No `id` field anywhere.** Every model's `id = SlugField(primary_key=True)` was previously
  populated straight from the source's own pre-computed slug. Now nothing ships one — the
  importer must derive one itself, and verify uniqueness before relying on it (a repeat of the
  "verify against every occurrence before trusting the pattern" discipline from the old known-
  issues list, applied to a new kind of assumption).
- **`srd` → `srd52`** (still boolean; also a new `basicRules2024` flag, unused so far).
  `image`/`gallery`/`otherVersions` are gone everywhere (no functional loss — nothing reads them).
- **A pervasive `"name|source"` (lowercased) reference-key convention** now links entries across
  files — spells, equipment, feats, optional features, classes/subclasses/features all reference
  each other this way, inside typed wrapper objects (`{"type": "refClassFeature",
  "classFeature": "Protector|Cleric|XPHB|1|XPHB"}` etc.) instead of bare strings. This is the
  single biggest reason the new data supports real FKs where the old one only supported free
  text.
- **Ability short codes** (`str`/`dex`/`con`/`int`/`wis`/`cha`) replace full names
  (`"Strength"`) as the reference form used everywhere (skills, classes, feats, species,
  backgrounds). A first-party `db/abilities.json` now ships the code↔name↔description mapping
  directly (see §3.1) — no more scraping a handbook table for this.
- **Structured choice objects** now appear across every domain:
  `{"choose": {"from": [...], "count": N}}` (or `"amount"`/`"weighted"` variants), replacing
  free-text "Choose N from ..." prose that used to need regex. This generalizes what
  `ChoiceDefinition` covered (~27 rows, background ability scores + one class's skill choice) to
  potentially every domain — species traits, feats, class starting proficiencies, background
  ability scores all use the same idiom now.
- Every catalog file sampled is **already pre-filtered to `source == "XPHB"`** — the
  `if sc.get("source") != "XPHB"` filtering the old `_import_classes` needs for subclasses is no
  longer necessary anywhere.

### Id-generation strategy

Every model derives its id as `slugify(name)` at import time (matching the old convention's own
output shape, e.g. `"Fire Bolt"` → `"fire-bolt"`) unless the new source already gives a natural
short code that's a better fit (`Ability` — see below). Because every file is pre-filtered to one
source, a bare `slugify(name)` should not collide within one catalog, but the importer verifies
this (raises loudly on collision) instead of assuming it — the exception is `Ability`, which uses
the source's own `short` field (`str`, `dex`, ...) as `id` directly, since that's the code
literally used everywhere else in the new data to reference an ability, not a derived slug.

### Reference-resolution strategy

Build one `{(name.lower(), source.lower()): pk}` lookup dict per referenceable model, populated
right after that model's own import step, before anything that references it runs. Resolve
`"name|source"` keys by lowercasing and splitting on `|`. `refClassFeature`/`refSubclassFeature`-
style keys can omit the trailing feature-source segment when it equals the class/subclass source
(see the Fighter example in §3.6) — match on `(name, className, classSource, level)` and tolerate
an optional trailing `|source`, don't require exact string equality.

## 2. Decisions made (confirmed with the user before implementing)

- **HandbookSection**: `db_old/handbook.json` was copied to `db/handbook.json`. `_import_handbook`/`_load_handbook` keep working exactly
  as they do today; no model or logic change needed here. `Ability` import switches away from
  scraping this file's "Ability Descriptions" table (see §3.1) now that `db/abilities.json`
  exists as a first-party source — `handbook.json` is now used for `HandbookSection` only.
- **`Spell.classes`/`Spell.subclasses`**: confirmed by direct search (not just the research
  agent's report) that no replacement exists anywhere in the new dump — not in `spells.json`
  (schema has no class-related key at all), not in `classes.json` (`additionalSpells` only covers
  bonus/granted spells, not full spell-list eligibility; no class carries an enumerated spell
  list), not in `rules.json`'s variant rules. All 391 spell names match exactly between
  `db/spells.json` and `db_old/spells.json` (verified: empty symmetric difference), so these two
  fields are populated from `db_old/spells.json`'s `classes`/`subclasses` arrays, joined by exact
  spell name (now extracted to `db/spell_classes.json`, Artificer already removed), as a **frozen supplemental source** — this is a deliberate, documented exception to
  "only `db/` is live source data," kept until upstream ships a real replacement. Flagged with a
  comment at the import site, not silently done.
- **Lore fields** (`Species.lore`, `Background.lore`, `Class.lore`): no fluff/foundry file ships
  in this `db/` drop yet (the user will add one later). The fields **stay on the models**;
  `_import_lore()` (a new, isolated step) looks for the expected fluff file(s) and populates them
  when present, and is a no-op (leaves `lore` empty, doesn't error) when they aren't — see §3.7
  for the extension point. Nothing about the rest of the import depends on lore being populated.

## 3. Per-domain mapping

### 3.1 Ability (`db/abilities.json`, was `db_old/handbook.json`'s table)

New shape: `{"ability": [{"name": "Strength", "short": "str", "source": "XPHB", "srd52": true,
"entries": ["Physical might."]}, ...]}` — 6 rows, one `entries` string each.

**Schema change**: `Ability.id` switches from `slugify(name)` (`"strength"`) to the source's own
`short` code (`"str"`) — this is the code every other domain uses to reference an ability, so
making it the actual PK removes a translation step everywhere else instead of adding one.
`description` populated from `entries[0]` (was the handbook table's second column; same kind of
one-line text either way).

### 3.2 Skill / Sense / Mastery / Language / Rule (small flat catalogs)

Same story for all five: top-level key renamed (`skill`/`sense`/`itemMastery`/`language`/
`variantrule`), `id` dropped (→ `slugify(name)`), `srd`→`srd52`. `Skill.ability` now reads a short
code (`"dex"`) directly — matches `Ability.id` post-§3.1 change with no translation.
`Rule.rule_type` is now a single-letter code (`"C"`) instead of the old spelled-out `"Core"` —
decoded via a small hardcoded map at import (`{"C": "Core", ...}` — only `"C"` appears in the
current 114 rows, but the map isn't assumed closed). `Language`'s old `typicalSpeakers` field is
gone; the new `origin` field is a different concept (the speaking people/plane, not prose) —
mapped to `Language.typical_speakers` on the reasonable assumption they serve the same display
purpose, but this should be spot-checked against a few rendered pages once imported.
`masteries.json`'s wrapper is bare `{"itemMastery": [...]}` (no `_meta`) — same fix, just note it
doesn't even have the `_meta` key most other new files do.

### 3.3 Equipment (`db/equipment-base.json` + `db/equipment.json`, was
`db_old/equipments.json` + `db_old/equipment_properties.json`)

The old flat 217-row catalog (`category` covering weapon/armor/gear/tool/instrument alike) splits
into `baseitem` (94 — weapon/armor stat blocks) + `item` (123 — everything else: gear, vehicles,
tools, foci, trade goods) — **94 + 123 = 217, an exact match**, confirming this is the same
catalog partitioned differently, not new content. Consistent with this project's existing
one-flat-`Equipment`-table philosophy (see the README's `Tool`/`SpellList`-removal rationale),
**both import into the same `Equipment` table** rather than splitting into separate
base-item/item models — a real schema upgrade here is giving `Equipment` proper FKs instead of
free text, not multiplying tables.

New reference catalogs, each promoted to a first-class model:

| New source | New model | Notes |
|---|---|---|
| `itemType` (23 rows, e.g. `{"name": "Melee Weapon", "abbreviation": "M"}`) | `EquipmentType` | Has a real `name` — the cleanest new catalog. `Equipment.category` (free text) becomes `Equipment.type` (FK), resolved via `baseitem.type`/`item.type`'s `"M\|XPHB"`-style ref. |
| `itemProperty` (9 rows) | `EquipmentProperty` (already exists) | No top-level `name` — display name lives at `entries[0].name`. `id` → `slugify(abbreviation)`. `Equipment.property_refs` (currently a raw `JSONField` list) becomes a real M2M. |
| `itemMastery` (8 rows, duplicated verbatim between `equipment-base.json` and `masteries.json`) | `Mastery` (already exists) | Import once from `masteries.json` (§3.2); `equipment-base.json`'s copy is redundant, ignored. `Equipment.mastery_refs` becomes a real M2M. |
| `itemGroup` (6 rows, e.g. "Arcane Focus" with `items: ["Crystal|XPHB", ...]` and `focus: ["Sorcerer", "Warlock", "Wizard"]`) | new `EquipmentGroup` | `focus` is a list of **class names** — a direct M2M to the existing `rules.Class`. Member items point back via `group: ["Arcane Focus"]` (name only) — resolve to `EquipmentGroup` by name, set `Equipment.group` (nullable FK). |
| `item.packContents` (e.g. Burglar's Pack → `["backpack|xphb", {"item": "candle|xphb", "quantity": 10}, ...]`) | new `EquipmentPackContent` through-model | Self-referential M2M on `Equipment` (`pack` FK, `content` FK, `quantity` default 1) — bare string entries default to quantity 1. |

`weight`/`value` moved from display strings (`"3 lb."`, `"15 gp"`) to bare numbers (value now in
copper, i.e. old-gp × 100) — `Equipment.weight`/`.value` become numeric fields instead of
`CharField`s; anything currently formatting them for display (`entries_render.py` or a template)
needs to add the unit/currency-conversion formatting that used to come for free from the source
string.

### 3.4 Spells (`db/spells.json`, was `db_old/spells.json`)

Count unchanged (391 → 391). Mechanical fields moved from display strings to structured
objects — `time` (list of `{number, unit, condition?}`, was `castingTime` string), `range`
(nested `{type, distance: {type, amount}}`, was a string), `duration` (list of `{type, duration?,
concentration?}`, was a string; `concentration` used to be its own top-level bool, now derived as
`any(d.get("concentration") for d in duration)`), `components` (dict `{v, s, m}`, `m` optionally
`{text, cost, consume}`, was a comma-joined string). **Decision: store these as `JSONField`s**
(richer than the old flattened strings, no re-derivation-with-information-loss) rather than
reconstructing display strings at import time — `entries_render.py`/any spell detail template
needs a small formatting helper for each, not a field rename.

`school` is now a single letter (`"V"`) — decoded via a hardcoded `SCHOOL_CODES` map (the 8
schools are a fixed, closed set; no catalog file ships this) back into the full word, same as the
model already stores today, so nothing downstream of `Spell.school` needs to change.

New FK: `savingThrow` (lowercase ability name list, e.g. `["dexterity"]` — full names here, not
short codes, unlike everywhere else — confirmed on Acid Splash) → `saving_throw_abilities` M2M to
`Ability`, matched case-insensitively by name. **Verified across all 391 spells before assuming a
shape**: length distribution is 237 with none, 146 with exactly one, and 8 with two or three
(Bigby's Hand, Earthquake, Prismatic Spray, Prismatic Wall, Storm of Vengeance, +2 more) — a single
nullable FK would have silently dropped data for those 8, so this is a M2M, not a FK.

`classes`/`subclasses`: see the decision in §2 — populated from `db_old/spells.json` by exact
name match, unchanged field shape/semantics on the model.

`ritual` moves from a top-level bool to `meta.ritual` per the schema — derive
`ritual = spell.get("meta", {}).get("ritual", False)`.

### 3.5 Species / Background / Feat / OptionalFeature

All four: top-level key renamed (`race`/`background`/`feat`/`optionalfeature`), `id` dropped,
`srd`→`srd52`, category/type fields recoded to short codes needing hardcoded decode maps if the
model should keep storing full words (`Feat.category`: `O`→Origin, `G`→General, `FS`→Fighting
Style, `EB`→Epic Boon, plus `FS:R`/`FS:P` sub-codes kept as-is if their exact meaning isn't
pinned down; `OptionalFeature.feature_type`: `EI`→Eldritch Invocation, `MM`→Metamagic,
`MV:B`→Maneuver, Battle Master — exhaustive: only these 3 codes appear in the current 58 rows).

**Species** (`db/species.json`, `race` key): **10 rows, down from 11** — `Grung` (source `VGM`,
already a documented one-off XPHB-exception in the old data) is genuinely absent from the new
dump, not filtered out by this project's own code; nothing to do here except update the expected
row count. `walkSpeed`/`flySpeed`/`swimSpeed`/`climbSpeed` are **completely gone** from every
entry — **verified this is a no-op in practice**: every one of the 10 surviving XPHB species
already had `fly=swim=climb=0` in the old data (only `Grung`, now dropped anyway, had a nonzero
`swimSpeed`). **Decision: drop `Species.fly_speed`/`swim_speed`/`climb_speed` entirely**
(zero real data loss, confirmed by direct check, not assumed); keep `walk_speed` as `speed`
(now a bare int, was `"30 ft."` string). New structured fields worth linking:
`darkvision` (bare int, new), `resist` (`{"choose": {"from": [damage-type codes]}}` — see
`ChoiceDefinition` below), `skillProficiencies`/`feats`/`additionalSpells` (species racial
grants — same choice/reference idiom as backgrounds/feats below). `size`/`creatureTypes` are now
code lists (`["S","M"]`, `["humanoid"]`) instead of prose (`"Small or Medium"`, `"Humanoid"`) — no
catalog exists for these (fixed small enums), kept as `JSONField` lists or decoded via a small
hardcoded map, whichever the frontend needs less rewriting for. 5etools' templating fields
(`_versions`/`_abstract`/`_mod`, used by Dragonborn's 10 color-ancestry variants) are **not**
expanded into separate rows — out of scope for this pass, noted so it isn't mistaken for a bug
later (Dragonborn imports as one row, same as today).

**Background** (`db/backgrounds.json`): 16 rows, unchanged. `ability` replaces the old free-text
`"Choose from Strength, Dexterity, Constitution"` with a fully structured, *weighted* choice
(`{"choose": {"weighted": {"from": ["str","dex","con"], "weights": [2,1]}}}`) — this closes a real
gap the old `ChoiceDefinition` had (`count` was always `null` since the source never gave a
number; now the weights make the +2/+1-vs-+1/+1/+1 split explicit). `skillProficiencies` (flat
bool-keyed grant, never a choice — matches the model's existing assumption) and `toolProficiencies`
(still a category placeholder + count, e.g. `anyGamingSet: 1`, not enumerated) replace the old
comma strings. `feats` references a `Feat` by `"name|source"` (was a bare name string). New
field with no old counterpart: `startingEquipment` (structured `A`/`B` option lists of
`{"item": "spear|xphb"}` / `{"value": 1400}`) — this data used to exist only as unparsed prose;
worth a new `Background.starting_equipment` `JSONField` (raw structured, resolved to `Equipment`
refs at read time or at import time into a through-model — recommend the latter, matching the
FK-maximizing goal, via a small `BackgroundStartingEquipmentOption` model:
`background, option ("A"/"B"), item FK nullable, quantity, gold_value nullable`).

**Feat** (`db/feats.json`): 77 rows, unchanged. `prerequisite` goes from a single free-text
string (flagged in the old README as never checked for the ability-vs-FK pattern) to a genuinely
structured list (`level`, `ability: [{code: N}]`, `feature: [...]`, `proficiency: [...]`,
`otherSummary`) — in one case (Grappler) demonstrably *more correct* than the old prose (Agonizing
Blast's old text omitted a level-2 requirement the new structured data makes explicit). Store the
raw structured list as `Feat.prerequisite` `JSONField` (heterogeneous shape — level/ability/
feature/proficiency/fallback-text mixed per entry — not worth forcing into several separate FK
columns given the variety). **Checked and rejected**: a `feature`-shaped prerequisite entry looked
like it might reference another `Feat` by name, but every one of the 10 occurrences is actually a
generic feature *category* name (`{"feature": ["Fighting Style"]}` — "you need a Fighting Style
feature", not "you need Feat X") — there is no feat-to-feat prerequisite anywhere in the source, so
no self-M2M was added; it stays inside the raw JSON. `ability`, `savingThrowProficiencies`,
`skillProficiencies`, `skillToolLanguageProficiencies`, `resist`, `senses`, `expertise`,
`additionalSpells` are all new structured grant fields with no prior counterpart — feed the same
generic choice/proficiency handling built for species/backgrounds (§3.5's `ChoiceDefinition`
note) rather than one-off Feat-specific code.

**OptionalFeature** (`db/optionalfeatures.json`): 58 rows, unchanged. `prerequisite` restructured
(class+level, spell-list filter, or nested optional-feature refs) same as Feat. New field
`consumes` (`{"name": "Superiority Die"}`) names the resource an optional feature draws from —
directly relevant to the CLAUDE.md "open design question" about where resource-spending logic
belongs; store as `OptionalFeature.consumes_resource_name` (`CharField`, free text — there's still
no resource catalog anywhere in `db/` to FK against, same gap `CharacterResource.name` already
has). `featProgression` (level→count map keyed by `Feat.category` code) is new; low priority,
store as `JSONField` if time allows, otherwise skip for this pass.

**Cross-cutting**: `Feature`'s extraction (`_named_dicts()` — top-level `{name, entries}` dicts)
is **unaffected** for all four domains — species/feat `entries` keep the identical shape.
`ChoiceDefinition`'s old regex-over-free-text approach is now obsolete and should be replaced with
a direct structural read: recursively walk any `entries` tree or grant field for
`{"choose": {"from": [...], "count"|"amount"|"weighted": ...}}` shapes, and this idiom now spans
species (`resist`, `skillProficiencies`, `feats`), backgrounds (`ability`), and feats (`ability`,
`savingThrowProficiencies`, `skillProficiencies`, `skillToolLanguageProficiencies`, `resist`) —
far beyond the old ~27-row baseline. `Proficiency`'s old `_flat_proficiency_items()` comma-split-
and-exclude-"Choose"-prefixed-items heuristic is similarly obsolete: flat grants are now
genuinely distinct in shape from choices (dict-of-bools vs. `{"choose": ...}`), so the split is
structural, not string-matched.

### 3.6 Classes (`db/classes.json`, was nested inside `db_old/classes.json`)

The new format **fully flattens** the old nesting into four top-level arrays — `class` (12),
`subclass` (48), `classFeature` (283), `subclassFeature` (309) — all already XPHB-filtered.
Features are independent, individually-addressable records carrying explicit back-references
(`className`/`classSource`/`level`, or `subclassShortName`/`subclassSource`) instead of living
nested inside their parent.

**README Issue 1 (subclass granting-level bundling) is structurally fixed**: the granting-level
wrapper (e.g. "Life Domain") is still its own record, but its real nested features ("Life Domain
Spells", "Disciple of Life", "Preserve Life") are now **already separate top-level
`subclassFeature` rows** — the wrapper points at them via `{"type": "refSubclassFeature",
"subclassFeature": "..."}` pointers in its own `entries`, rather than nesting them inline. No
`_split_subclass_features()`-style unbundling heuristic is needed anymore. One decision remains,
not a parsing problem: the wrapper's own `entries` cleanly separates flavor-text strings from
`refSubclassFeature` pointer dicts (trivial filter) — **keep the existing behavior**: the flavor
strings become `Subclass.description` (as today), the wrapper record itself is *not* imported as
its own `Feature` row (it would be a pure duplicate of its sibling pointers, the same "redundant
storage" pattern as Issues 2/4 in the old known-issues list), and the pointed-to features import
normally, resolved by the `refSubclassFeature` key.

Per-level progression is now real structured data instead of one opaque `columns` blob:

- **Spell slots**: `classTableGroups[].rowsSpellProgression` — 20 rows of `list[int]` (slots per
  spell level 1–9), separate from the general `table`. Same shape for subclasses
  (`subclassTableGroups[].rowsSpellProgression`, e.g. Eldritch Knight).
- **Cantrips/known/prepared counts**: `cantripProgression`, `preparedSpellsProgression`/
  `preparedSpellsChange`, `spellsKnownProgressionFixed(ByLevel)` — flat `list[int]` per level.
- **Resource dice/bonus table cells**: typed objects inside `classTableGroups[].rows` —
  `{"type": "dice", "toRoll": [{"number": 1, "faces": 6}]}` (Monk Martial Arts die),
  `{"type": "bonus", "value": 2}` (Barbarian Rage Damage), `{"type": "bonusSpeed", "value": 0}`
  (Monk Unarmored Movement) — alongside plain int/str cells still occurring for other columns.

**Schema change**: split `ClassLevel.columns` (currently one JSON blob per row) into: a real
`spell_slots` `JSONField` (from `rowsSpellProgression`, list of 9 ints) when the class casts;
`cantrips_known`/`spells_prepared` int fields from the flat progressions; and keep a slimmed-down
`columns` JSON blob only for whatever's left over (non-spellcasting resource columns, which stay
JSON since their shape is genuinely per-class and typed-cell parsing per column is a bigger
project than this pass needs — store the raw typed cell object, don't flatten it to a display
string, so no information is lost even though it isn't split into dedicated fields).
`Class.spellcasting_ability` (new FK to `Ability`), `Class.caster_progression` (new `CharField`:
full/half/third/pact/none) are worth adding directly on `Class` — cheap, high-value, no
ambiguity.

**New `ChoiceDefinition` source**: `{"type": "options", "count": N, "entries": [{"type":
"refClassFeature", ...}, ...]}` nodes appear inside `entries` trees (e.g. Cleric's level-1 Divine
Order choice between "Protector"/"Thaumaturge"). Far better than the old regex over
`Class.proficiencies` free text — `count` is a real int, options resolve to concrete
`classFeature`/`subclassFeature` rows, not a comma-split string. Walk `entries` trees recursively
for this node type rather than checking one known field, since it can appear anywhere.

**Proficiencies**: `startingProficiencies.{armor,weapons}` are flat lists (no more comma-parsing);
`armorProficiencies` mirrors `armor` as a bool-dict; `skills` is the same `{"choose": {"from",
"count"}}` idiom as everywhere else. `toolProficiencies` remains per-class ad hoc dict shapes
(`{"anyMusicalInstrument": 3}`, `{"thieves' tools": true}`) — this is the direct structured
analogue of the two cases (Bard/Monk) the old `Proficiency` docstring called out as unparseable
free text and deliberately dropped. **Now worth modeling** (real JSON, not prose) rather than
continuing to drop it — store as `Proficiency.choice_data` `JSONField` on the relevant rows
instead of silently excluding them.

**New fields with no prior model home**: `multiclassing.proficienciesGained` (was always `null` in
the old dump — genuinely new data, mirrors `startingProficiencies`' shape); `startingEquipment`
(same `A`/`B`/`C`-option shape as `Background.startingEquipment`, reuse the same through-model
approach from §3.5); `additionalSpells` (bonus spells by class/subclass — same `name|source` spell
refs as species, resolve to `Spell` FKs); `consumes` on `classFeature`/`subclassFeature`
(`{"name": "Channel Divinity", ...}` — same CLAUDE.md-relevant resource-name field as
`OptionalFeature.consumes`, §3.5 — store the same way, `Feature.consumes_resource_name`).
`gainSubclassFeature: true` is now an explicit flag on the subclass-grant level in
`class.classFeatures[]`, replacing the old implicit "feature literally named 'Subclass Feature'"
string-match this project's importer never actually needed (subclasses were already handled via
the `subclasses` nested list, not this flag) — no code depends on this, noted for completeness
only.

No `Class.lore`/fluff source ships (see §2's lore decision — applies here too, `Class` included).

### 3.7 Lore / fluff (implemented once `db/fluff-*.json` shipped)

`_import_lore()` is a separate step (not folded into `_import_species`/`_import_backgrounds`/
`_import_classes`) that runs after every other import, matching each fluff entry to its already-
imported row by name and updating `.lore`. Kept separate so it degrades gracefully via
`_load_if_exists()` if a fluff file is ever missing again (a no-op, not a crash), rather than a
conditional wedged into each domain's main import function.

Once `db/fluff-*.json` actually arrived (six files: `fluff-backgrounds`, `fluff-classes`,
`fluff-equipment`, `fluff-feats`, `fluff-species`, `fluff-spells`), only three turned out to have
real lore text at all:

- `fluff-species.json` (`raceFluff`) → `Species.lore`, all 10 species.
- `fluff-backgrounds.json` (`backgroundFluff`) → `Background.lore`, all 16 backgrounds.
- `fluff-classes.json` (`classFluff`) → `Class.lore`, all 12 classes. The same file's
  `subclassFluff` (48 rows) was checked too — zero of them carry an `entries` key, only `images`
  (art credits) — so `Subclass` (no `lore` field to begin with, only `description`, already
  sourced from the primary `db/classes.json`) is untouched.
- `fluff-feats.json` and `fluff-equipment.json` carry only `images` for every single row (8 and
  54 respectively) — verified, not assumed — so `Feat`/`Equipment` (neither has a `lore` field)
  have nothing to gain here, consistent with this project's standing choice to drop art-asset
  fields everywhere.
- `fluff-spells.json` (51 of 391 spells) is `{name, source, images}` only — no `entries` key
  exists anywhere in the file's schema, so there's no spell lore to import at all.

Each fluff entry's `entries` value is stored **verbatim**, unchanged in shape from every other
`entries`-shaped field this project already renders generically via `render_entries()` - no
unwrapping needed even though species fluff nests its prose two `{"type": "entries", "entries":
[...]}` levels deep, deeper than a flat `Background.entries` list - the renderer already handles
arbitrary nesting.

### 3.8 `foundry-*.json` — checked, not integrated

Six more files shipped alongside the fluff ones: `foundry-classes`, `foundry-equipment`,
`foundry-feats`, `foundry-optionalfeatures`, `foundry-species`, `foundry-spells`. These are
Foundry VTT compendium exports - `activities`/`effects`/`advancement` blocks encoding automation
formulas (dice rolls, active-effect changes like `system.attributes.hp.tempmax` ADD 5), not
narrative content. Specifically checked (not assumed) for a class↔spell-list association, since
that's the one piece `db/spells.json` is missing (see §2/§3.4) - **none exists anywhere in these
files either**. `foundry-classes.json`'s `class`/`subclass` entries carry only `ScaleValue`
advancement (resource scaling by level threshold, e.g. Barbarian's Rage Damage/Rages) with no
spell references at all; `foundry-spells.json`'s spells carry only their own casting
automation (`activities`/`effects`), no `classes` field; a literal substring search for "classes"
across every foundry file turned up exactly one hit (`foundry-optionalfeatures.json`), which was
incidental text inside an unrelated JSON blob, not a real association.

Two more things worth noting about this data, in case it's revisited later:

- **Every foundry file is a partial subset**, not a full mirror: 10/12 classes (missing Warlock
  and Wizard), 11/48 subclasses, 41/77 feats, 51/58 optional features, 295/391 spells, and
  equipment is barely covered at all (1 baseitem + 23 items out of 217). It can't become a
  primary source for anything - at best a supplementary enrichment layer for the rows it does
  cover.
- **Not imported in this pass** - deliberately left as a decision for later, not a gap: the
  `activities`/`effects` automation data is exactly the kind of mechanical detail
  `builder.services.effects`/`derived_stats` (still docstring-only stubs) would eventually need,
  but designing a relational model for Foundry's effect-change schema is a real modeling project
  in its own right, not a straightforward field-mapping exercise like the rest of this migration -
  raised with the project owner rather than assumed.

## 4. Summary of schema changes

New models: `EquipmentType`, `EquipmentGroup`, `EquipmentPackContent` (through),
`BackgroundStartingEquipmentOption` (through), `ClassStartingEquipmentOption` (through, same
shape as background's).

Changed models:; `Ability` (PK becomes short code); `Skill`/`Sense`/`Mastery`/`Language`/`Rule`
(id derivation only, no field changes); `Equipment` (`category`→`type` FK,
`property_refs`/`mastery_refs`→real M2Ms, `weight`/`value`→numeric, new `group` FK, new pack
contents M2M); `Spell` (`school` unchanged in shape, `casting_time`/`range`/`duration`/
`components`→`JSONField`, new `saving_throw_abilities` M2M, `classes`/`subclasses` re-sourced from
`db_old` but unchanged shape); `Species` (drop `fly_speed`/`swim_speed`/`climb_speed`, `speed`
becomes int, new `darkvision` int field); `Background` (new `starting_equipment` through-model);
`Feat` (`prerequisite`→`JSONField`, no self-M2M — checked, rejected, see §3.5); `OptionalFeature` (new
`consumes_resource_name`); `Class` (new `spellcasting_ability` FK, `caster_progression`, new
starting-equipment through-model); `ClassLevel` (new `spell_slots`/`cantrips_known`/
`spells_prepared` fields alongside a slimmed `columns`); `Feature` (new
`consumes_resource_name`); `Proficiency` (new `choice_data` JSONField for the two previously-
dropped tool-choice rows). `HandbookSection`: unchanged.

This is the reference for the implementation pass that follows — model/migration changes, then
`import_rules_data.py`'s full rewrite, then a re-check of every service/schema/frontend template
that reads a changed field shape (`apps/rules/services/*.py`, `apps/rules/schemas.py`,
`apps/frontend/entries_render.py` and its templates) — done as the next step, not in this
document.


## 5. Post-migration fixes (found after initial deployment)

Two bugs surfaced once real usage exercised paths the initial migration's own verification
missed - written up here for the same reason as every fix above: not because this list is
expected to be complete, but so the same *kind* of gap is easier to recognize next time.

**Starting equipment was imported but never displayed.** `ClassStartingEquipmentOption`/
`BackgroundStartingEquipmentOption` were built and populated correctly (93/108 rows) in the
initial pass, but no frontend view ever read them - `apps/frontend/views.py` had no code path
touching `starting_equipment_options` at all. Caught when asked directly "why isn't this
displayed," not by any test (there wasn't one covering "does the detail page show every field the
model has"). Fixed by adding a "Starting Equipment" section to both `world_class_detail` and
`world_background_detail`, backed by a new `render_starting_equipment()` in `entries_render.py`,
and removing `world_background_detail`'s old `_extract_named_entry(bg.entries, "Equipment:")`
prose extraction - a straight duplicate of the same information once the structured version
existed, same "redundant storage" pattern flagged repeatedly in the original migration write-up.

**Two starting-equipment picks resolve to a group, not an item.** While wiring up the display
above, Acolyte's page 500'd: `BackgroundStartingEquipmentOption.item` and `.gold_value` were both
`None` for its "Holy Symbol" pick, which `render_starting_equipment()` didn't handle. Root cause:
`"holy symbol|xphb"` isn't a concrete `Equipment` row at all - it's a reference to the
`EquipmentGroup` named "Holy Symbol" (Amulet/Emblem/Reliquary are the actual choices), the same
`itemGroup` catalog `Equipment.group` already resolves against (see §3.3). Verified this is the
*only* unresolved shape - a script diffed every `startingEquipment` item reference across both
`db/backgrounds.json` and `db/classes.json` against the full `Equipment` name set, and exactly two
names failed to match, both confirmed `EquipmentGroup` names ("Holy Symbol", "Druidic Focus").
Fixed by adding a `group` FK (mirroring `Equipment.group`) to both `*StartingEquipmentOption`
models, resolving against `EquipmentGroup` as a fallback when the `Equipment` lookup misses, and
hardening `render_starting_equipment()` to render a group pick as "any Holy Symbol" instead of
crashing on the case it didn't anticipate.

**Separately, not a bug but a rendering gap**: `ClassLevel.columns` cells that use the source's
typed `{"type": "dice"/"bonus"/"bonusSpeed", ...}` shape (kept verbatim in the DB on purpose, see
§3.6) were never decoded for display, so the Level Progression table showed the raw Python dict
repr (e.g. `{'type': 'dice', 'toRoll': [{'faces': 6, 'number': 1}], 'rollable': True}`) instead of
"1d6". Fixed with a `_format_table_cell()` step in `render_key_value_table()` - decoding stays a
frontend concern, the DB keeps the raw structured value.

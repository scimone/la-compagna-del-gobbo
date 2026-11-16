# la-compagna-del-gobbo

A D&D 5.5e (2024 rules) backend for player logic: characters, character creation/leveling, and the
static rules catalog they're built from.

See [architecture.md](architecture.md) for the full design rationale. This README documents what
exists today and what each placeholder is reserved for.

## Tech stack

- **Django** — models and persistence
- **PostgreSQL** — the database (via `docker-compose.yml`)
- **django-pwa** — PWA manifest/service-worker plumbing for the frontend shell
- **WhiteNoise** — serves collected static files (PWA icons, menu artwork, `serviceworker.js`)
  directly from the ASGI app when running in the `dnd-web` container - there's no separate web
  server sharing a volume, and uvicorn doesn't serve static files on its own the way
  `manage.py runserver` does
- **uvicorn** — ASGI server (3 worker processes in Docker)
- **uv** — dependency management
- **Docker** / **docker-compose** — containerized deployment (`Dockerfile`, `docker-compose.yml`)
- **pytest** / **pytest-django** — tests
- **ruff** — linting and formatting

## Running it

Copy `.env.dist` to `.env` and fill in a password/secret key. `.env` is read by both `manage.py`
(via `python-dotenv`, host-side) and by Docker Compose (`env_file:`) — which `POSTGRES_HOST`/
`POSTGRES_PORT` belong there depends on which of the two ways below you're running.

### Option A — everything in Docker (closest to how it's actually deployed)

```bash
docker compose up -d --build
```

This builds `dnd-web` (the Dockerfile installs deps with `uv sync`, then runs
`collectstatic --noinput` at build time - see `STORAGES`/WhiteNoise below) and starts it
alongside `dnd-db` (Postgres 16, `postgres_data/` bind-mounted for persistence; `dnd-web` gets `./media` bind-mounted the same way, for the pictures players upload). `dnd-web` waits
for `dnd-db` to report healthy (`pg_isready`) before starting, and its startup command runs
`manage.py migrate --noinput` automatically before uvicorn. `import_rules_data` does **not**
run automatically (see the warning below) - do it once, manually:

```bash
docker compose exec dnd-web uv run manage.py import_rules_data
```

For this mode, `.env`'s `POSTGRES_HOST`/`POSTGRES_PORT` should point at the `dnd-db` service on
the compose network (`dnd-db` / `5432`, per `.env.dist`) - or at an external Postgres instance
reachable from the container, if you'd rather not use the bundled `dnd-db` at all (in which case
that service just goes unused; nothing requires the app to talk to it). App: `http://localhost:3000/`.

**Redeploying** after a code change: `bash update-app.sh` — rebuilds the image from the working tree (no
`git pull`, so no GitHub credentials needed) and restarts only `dnd-web` (`dnd-db` and its data are left running untouched).

After changing anything under `db/it/` (the Italian game-content translations), load it with
`docker compose exec dnd-web uv run manage.py import_translations` — unlike `import_rules_data`
(next warning) this only syncs the translated models' rows (the handbook, so far - English and
Italian text, creating/updating/deleting just those), wipes nothing else, and is safe to re-run
any time.

⚠️ **`import_rules_data` wipes and reloads every `rules` table.** Every FK from `characters` into
`rules` is `on_delete=PROTECT`, so running it again once real `Character` rows exist will raise
`ProtectedError` and refuse - it's meant as a one-off/rare data-refresh step, never part of the
normal startup or redeploy path.

### Option B — Postgres in Docker, `manage.py`/uvicorn on the host (day-to-day dev)

This is the faster loop for iterating on code, and what this whole project has been developed
against. Start just the database:

```bash
docker compose up -d dnd-db
```

`.env`'s `POSTGRES_HOST`/`POSTGRES_PORT` are the in-network values for the `dnd-db` container;
from the host, override them to the mapped port instead:

```bash
export POSTGRES_HOST=localhost POSTGRES_PORT=5462  # matches the "5462:5432" port mapping
uv run python manage.py migrate
uv run python manage.py import_rules_data  # loads db/*.json into the rules tables
uv run uvicorn config.asgi:application --reload
```

Static files (PWA icons, menu artwork, `serviceworker.js`) are served differently here than in
the container: `manage.py runserver` auto-serves them under `DEBUG=True`; running `uvicorn`
directly instead (as above) needs `staticfiles_urlpatterns()`, which `config/urls.py` appends to
`urlpatterns` whenever `DEBUG` is on - no `collectstatic`/`STATIC_ROOT` involved for this path,
unlike the container's WhiteNoise setup.

Tests need the same host override as above (`pytest-django` creates/drops a throwaway test
database using the same connection settings):

```bash
POSTGRES_HOST=localhost POSTGRES_PORT=5462 uv run pytest
uv run ruff check .
```

## Conventions

- **One file per domain concept.** Models live one-per-file under `models/`, re-exported from
  `models/__init__.py`. Service functions are grouped one-file-per-domain under `services/`.
- **No public API.** This is a pure server-rendered frontend: the only HTTP surface is the HTML
  views in `apps/frontend/` (plus `/i18n/setlang/` and the PWA manifest/service worker); there is no admin site either.
  There is no REST/JSON API, no OpenAPI schema and no Django Ninja - it was removed on purpose to
  keep the attack surface of an internet-facing deployment as small as possible. Don't add one back.
- **No business logic in views.** Views call into `services/` (plain functions over
  querysets/instances) - `rules`, `characters` and `builder` are all consumed this way.
- **`rules` is read-only.** It's populated via `manage.py import_rules_data` (see
  [apps/rules/management/](apps/rules/management/)), never through the UI.

## App boundaries

Three Django apps form the actual game-logic layering. A small `campaigns` app sits beside
`rules` (it owns who is in which campaign and knows nothing about characters), and `frontend`,
covered in its own section below, is the web UI shell, not part of this layering:

```
rules        static 5.5e game content (classes, species, spells, equipment, ...)
   │         referenced by
   ▼
characters   persisted character state (owns no game rules, only references them)
   │         manipulated/resolved by
   ▼
builder      character creation/leveling engine (mostly logic, few/no models)
```

## Model status

`rules` is the only app with a static data source ([db/](db/), XPHB-only) — this table is about
whether each model can honestly be populated from that source. `characters` has no data source
of its own to import (it's persisted app state, not static content) but its models now have real
fields too — see the [`apps/characters/`](#appscharacters--persisted-character-state) section
below, and the design decisions called out there. `builder` still has no models — see its
section for why.

**`db/` was replaced wholesale in 2025** with a rawer, more cross-referenced source dump (the
previous format's one still-needed field, `Spell.classes`/`subclasses`, now lives in
`db/spell_classes.json`, see below). The table below describes the *current* `db/`
format; the "Known data-import issues" section further down is historical - it documents bugs
found while building the import against the *old* `db_old/` format and is left as-is for that
reason, not updated for the new one. See
[docs/data_migration_2025.md](docs/data_migration_2025.md) for the 2025 migration's own write-up
(the new format's shape, the field-by-field mapping decisions, and the three data-loss tradeoffs
resolved with the project owner: `Spell.classes`/`subclasses` merged from the old dump (`db/spell_classes.json`), lore fields
(now populated - see below) initially left empty pending a fluff-data drop, `HandbookSection`
kept on `db/handbook.json` copied verbatim from the old dump).

| Model | Status | Source | Notes |
|---|---|---|---|
| `Rule` | Defined | `db/rules.json` (`variantrule`) | 114 rows |
| `Skill` | Defined | `db/skills.json` | `ability` is a FK to `Ability`, keyed by the source's own 3-letter short code (`str`/`dex`/.../`cha`) — see `docs/data_migration_2025.md` §3.1 |
| `Ability` | Defined | `db/abilities.json` | 6 rows (Strength, Dexterity, Constitution, Intelligence, Wisdom, Charisma) - a first-party source now (was scraped from `db_old/handbook.json`'s "Ability Descriptions" table). `id` is the source's own short code (`str`, `dex`, ...), not a slugified name - every other domain references abilities by this same code. Referenced by `Skill.ability`, `Class.primary_abilities`/`saving_throw_abilities`/`spellcasting_ability`, `Spell.saving_throw_abilities` |
| `Sense` | Defined | `db/senses.json` | |
| `Condition` | Defined | `db/conditions.json` (`condition` + `status` lists) | 18 rows: the 15 conditions (`kind="condition"`) and Bloodied/Concentration/Surprised (`kind="status"`). Only the rules text is data; what each does to the numbers is `apps/characters/conditions.py` (keyed by the same ids, checked by `test_conditions.py`) |
| `Mastery` | Defined | `db/masteries.json` | |
| `EquipmentType` | Defined | `db/equipment-base.json` (`itemType`) | 23 rows. New - the old format had no such catalog, only a free-text `Equipment.category` string. `Equipment.type` FKs here now |
| `EquipmentGroup` | Defined | `db/equipment.json` (`itemGroup`) | 6 rows. New - a named category of interchangeable items (e.g. "Arcane Focus"); `focus_classes` M2Ms to `Class` |
| `EquipmentProperty` | Defined | `db/equipment-base.json` (`itemProperty`) | 9 rows. No top-level `name` in the source (display name lives at `entries[0].name`) - `id` is `slugify(abbreviation)` |
| `Equipment` | Defined | `db/equipment-base.json` (`baseitem`, 94 rows) + `db/equipment.json` (`item`, 123 rows) | 217 rows total - an exact split of the old single flat catalog, not new content. `type`/`properties`/`masteries`/`group` are real FKs/M2Ms now (were a free-text `category` plus JSON ref lists); `pack_contents` is a new self-M2M (`EquipmentPackContent`) for pack contents (e.g. Burglar's Pack -> Backpack, Candles, ...) |
| `EquipmentPackContent` | Defined | `db/equipment.json` (`item.packContents`) | 65 rows. New - resolves a pack's contents to real `Equipment` FKs with a quantity, where the old format left this as unparsed prose |
| `Species` | Defined | `db/species.json` (`race`) | 11 rows - 10 XPHB plus `Grung` (source VGM), which is absent from the new source drop as shipped (not filtered by this project) and was added back by hand afterward, at the project owner's request, converting `db_old/species.json`'s row into the new format - see `SPECIES_SHORT_DESCRIPTIONS` in `import_rules_data.py`. `fly_speed`/`swim_speed`/`climb_speed` were dropped (no source left for them, and verified zero real data loss - every surviving species already had all three at 0, including the hand-added `Grung`); `speed` is now a plain int. `darkvision` is new. `resistances`/`additional_spells`/`lineages` are new (character builder): flat damage resistances (Aasimar, Dwarf), unconditional species spells (Aasimar's Light), and the source's `_versions` normalised to one lineage shape (Elf, Gnome, Goliath, Tiefling, Dragonborn colours) - see the model docstring |
| `Background` | Defined | `db/backgrounds.json` | `skills` is a real M2M to `Skill` now (was a comma string); `feat` is a real FK to `Feat` now (was a bare name string), with `feat_variant` keeping the source's `; cleric`/`; druid`/`; wizard` suffix (Magic Initiate) that the FK alone loses; `ability_scores`/`tools` keep the source's own structured choice/grant JSON rather than a free-text summary |
| `BackgroundStartingEquipmentOption` | Defined | `db/backgrounds.json` (`startingEquipment`) | 108 rows. New - a background's "choose A or B" starting gear, resolved to real `Equipment` FKs (or a gold value) where the old format left this as unparsed prose. Two picks (e.g. Acolyte's "Holy Symbol") name an `EquipmentGroup` instead of one concrete item - a `group` FK covers those; displayed on the background/class detail page as a "Starting Equipment" section |
| `Feat` | Defined | `db/feats.json` | `prerequisite` is a structured JSON list now (ability/level/feature/proficiency requirements), not one free-text string. `additional_spells`/`grants` are new (character builder): Magic Initiate's spell lists and the proficiency-grant keys (Skilled, Musician, Crafter, Tavern Brawler, ...) |
| `Class` | Defined | `db/classes.json` (`class`) | Core metadata; `weapon_proficiencies` falls back to the source's `weapons: ["simple", "martial"]` list for the ten classes that have no structured grant (was silently empty); per-level progression is `ClassLevel`. `armor_proficiencies`/`weapon_proficiencies`/`tool_proficiencies` are the source's own structured JSON now (were comma-separated text); the old free-text `proficiencies` summary field and skill-choice regex are gone (see `ChoiceDefinition`). `spellcasting_ability`/`caster_progression` are new. `primary_ability_conjunction` ("or" vs "and") is now derived structurally from the source's own shape instead of a string-pattern parse — see `docs/data_migration_2025.md` §3.6 |
| `ClassLevel` | Defined | `db/classes.json` (`class.classTableGroups`/spell progressions) | `spell_slots`/`cantrips_known`/`spells_known_or_prepared` are dedicated fields now (the source gives these as structured per-level progressions); `columns` keeps whatever's left (e.g. Barbarian's Rages/Rage Damage, Warlock's pact-magic Slot Level) |
| `ClassStartingEquipmentOption` | Defined | `db/classes.json` (`class.startingEquipment.defaultData`) | 93 rows. New - same shape as `BackgroundStartingEquipmentOption`, for a class's own starting-gear choice |
| `Subclass` | Defined | `db/classes.json` (`subclass`, 48 rows) | Already pre-filtered to XPHB in the source (no more `if source != "XPHB"` filtering needed). `additional_spells` (bonus spells) is new. `description` is still the granting level's flavor text, but the new source already keeps it as its own addressable record pointing at its sibling features via `refSubclassFeature` markers rather than bundling them inline - see [Known data-import issues](#known-data-import-issues) Issue 1 and `docs/data_migration_2025.md` §3.6 for how this changed |
| `SubclassLevel` | Defined | `db/classes.json` (`subclassFeature`) | A pure level marker - no `features` field of its own; its features are the `Feature` rows FK'd back to it |
| `Spell` | Defined | `db/spells.json` | `casting_time`/`range`/`duration`/`components` are structured `JSONField`s now (the source gives nested objects, not display strings). `saving_throw_abilities` is new (a M2M - up to 3 spells name more than one ability, verified against all 391). `classes`/`subclasses` are a deliberate exception: the new source dropped this data with no replacement anywhere, so these two fields are still populated from `db_old/spells.json` by exact name match — see `docs/data_migration_2025.md` §2/§3.4 |
| `Language` | Defined | `db/languages.json` | |
| `OptionalFeature` | Defined | `db/optionalfeatures.json` | `additional_spells` (the source's `additionalSpells`) is what gives an invocation its spells - Pact of the Chain's Find Familiar, Armor of Shadows' Mage Armor, ..., Pact of the Tome's picks; they land as `CharacterSpell` rows with `source="option:<id>"` and `free_cast_unlimited`, and go when the invocation is replaced. `prerequisite` is structured JSON now, same treatment as `Feat.prerequisite`. `consumes_resource_name` is new (names the resource a pick spends, e.g. "Superiority Die" - relevant to spending a resource, see `characters.services.play` and CLAUDE.md "Where spending lives") |
| `Proficiency` | Defined | `db/classes.json`, `db/backgrounds.json` | 47 rows - `Background.skills` moved off this model entirely (a real M2M now, see `Background`). `choice_data` is new: the two previously-excluded tool-proficiency choices (Bard's/Monk's) are now included, since the source gives them as real JSON instead of unparseable "Choose N ..." prose |
| `Feature` | Defined | `db/classes.json`, `db/species.json`, `db/feats.json` | 723 rows (271 class, 265 subclass, 65 species - 24 of them one-per-lineage cuts, see `rules/lineage_features.py` -, 122 feat). Class/subclass feature resolution now walks `refClassFeature`/`refSubclassFeature` pointers recursively (a class/subclass's own feature-list field doesn't always enumerate every feature - some are only reachable via a pointer inside a sibling feature's `entries`, e.g. Cleric's Divine Order choice or a subclass's granting-level wrapper) rather than reading one flat list - see `docs/data_migration_2025.md` §3.6. A pointer target marked with a `header` field (5etools' own "this is a sub-entry, not standalone" marker) is inlined into whichever feature points at it instead of becoming its own row - see [Known data-import issues](#known-data-import-issues) Issue 6. `consumes_resource_name` is new, same as `OptionalFeature`'s |
| `Effect` | Partly defined | derived from `Feature.entries` | 2094 rows (independently cross-checked against the pre-migration verified-correct count) |
| `ChoiceDefinition` | Partly defined | `db/species.json`, `db/backgrounds.json`, `db/classes.json`, `db/feats.json` | 85 rows (up from 27) - the source's own `{"choose": {"from": [...], "count"|"amount"|"weighted": ...}}` idiom replaced the old regex-over-free-text approach and extends to far more of the data (species racial choices, feat ability/skill/save choices, not just the two cases the old format could reliably pattern-match) |
| `HandbookChapter` | Defined | `db/handbook.json` (`data`, level-1 items) | 5 rows - "Playing the Game", then the SRD chapters "Character Origins", "Feats", "Equipment" and "Spells" (`db/handbook.json` gained four level-1 items from `handbook_extended.md`, the SRD 5.2.1 rules text of those chapters). Holds just the chapter's name (`name`/`name_en`/`name_it`, Italian from the SRD's own chapter titles) - the Handbook menu shows it as a toggle heading over its sections. A chapter's own unnamed leading text (the "Playing the Game" intro narrative, no Italian source) is not imported |
| `HandbookSection` | Defined | `db/handbook.json` (`data`) | 22 rows: each chapter's direct named children (12 for "Playing the Game" - 15 in the source, "Rules Glossary" and "Player or DM?" are left out, see the i18n section; then Character Backgrounds / Species / Classes, Feat Descriptions, Coins / Weapons / Armor / Tools, Gaining Spells / Casting Spells), each pointing at its `chapter`. The "Playing the Game" part of the file is copied verbatim from `db_old/handbook.json` (the new `db/` drop ships no replacement) - a deliberate exception, same as `Spell.classes`/`subclasses`; the SRD chapters were added later, converted from the PDF-extracted text (page numbers of those sections are the XPHB pages inferred from the other `db/` files, e.g. the weapon-property and mastery pages, so a couple are best estimates). `entries` holds each one's own content (arbitrarily nested headings/lists/tables/insets), rendered the same way as every other `entries`-shaped field. **First translated model** - `name`/`entries` also have `_en`/`_it` columns, the Italian side loaded from `db/it/handbook.json` (see [Internationalization](#internationalization-i18n)); `self_translated_fields` marks the part hand-translated for this project ("Character Classes", which the SRD lacks). Surfaced two edge cases in `entries_render.py` itself - see [Known data-import issues](#known-data-import-issues), Issue 3 |

`Species.lore`/`Background.lore`/`Class.lore` are populated from `db/fluff-species.json`/
`fluff-backgrounds.json`/`fluff-classes.json` (added after the initial 2025 migration - all 10/16/
12 rows have real lore text). `db/fluff-feats.json`/`fluff-equipment.json`/`fluff-spells.json`
carry only art credits (`images`), no text, for every row - checked, not assumed - so `Feat`/
`Equipment`/`Spell` gain nothing from them (none has a `lore` field). `db/foundry-*.json` (Foundry
VTT automation exports, added at the same time) were checked too, specifically for a `Spell`↔
`Class` list association - none exists there either, and every foundry file only partially covers
its domain (e.g. 295/391 spells, 10/12 classes) - not imported; see
`docs/data_migration_2025.md` §3.7/§3.8.

Every "Defined" model is loaded end-to-end (all 217 equipment rows, all 391 spells, all 12
classes × 20 levels, all 19 languages, all 58 optional features, etc. — no rows dropped or
truncated) by `manage.py import_rules_data` (`apps/rules/management/commands/`), which wipes
and reloads every `rules` table from `db/` in one transaction. `Proficiency`'s row count (47)
and `Effect`'s (2094, matching the pre-migration verified-correct count exactly) were both
independently cross-checked against a from-scratch recomputation; `Effect` and
`ChoiceDefinition` are "Partly defined" because they only cover the subset of their source
that's reliably, mechanically extractable — see their model docstrings for exactly what was
included and excluded, and why.

`Tool` and `SpellList`, both originally listed in architecture.md, were removed entirely (not
just left "Missing") once it was clear they'd always be pure duplicates: a Tool is just an
`Equipment` row whose `type` is one of `{Tool, Artisan's Tools, Instrument, Gaming Set}`, and a
class's spell list is just `Spell.classes`/`Spell.subclasses` filtered — a dedicated table would
carry the same rows twice with no independent reason to exist.

### Known data-import issues

Not every model above is guaranteed bug-free or non-redundant just because it's "Defined" -
that only means the source was mapped field-for-field. This also covers `apps/frontend/
entries_render.py`, not just the import command - the same "assumed a shape from a handful of
examples, an edge case elsewhere in `db/` breaks it" failure mode shows up at render time too,
not only at import time. Problems found so far, none visible from a row count or a JSON diff,
all fixed, all written up here so the same *kind* of problem is easier to recognize in whatever
table (or tag, or shape) turns up next - not because this list is expected to be complete.

#### Issue 1: a subclass's granting-level features were bundled into one fake feature

**The bug**: `db/classes.json`'s subclass `features` list is *supposed* to be one block per
feature (`{level, name, entries}`, exactly like `Class.features`), and for most levels it is.
But at the level a subclass is actually gained (its lowest level, e.g. level 3 for a Fighter
subclass), the source instead gives it a *single* block titled after the subclass itself, which
bundles that level's real named features as nested sub-entries, plus a couple of plain-text
flavor-text paragraphs, all inside that one block. Naively importing this made every subclass's
first level look like one giant feature named after the subclass (e.g. Monk's "Warrior of
Mercy" swallowing "Hand of Harm"/"Hand of Healing"/"Implements of Mercy" into itself) instead of
several separate features that merely share a level.

**How it was caught**: this *looks* fine in a raw JSON diff or a row count - the data is exactly
as "complete" either way, just organized differently - so it only became obvious once the World
UI rendered each subclass's features as individual cards (see `render_class_features()` in
`apps/frontend/entries_render.py`) and one level's card visibly held three unrelated feature
names crammed under one heading.

**The fix** (`_split_subclass_features()` in
`apps/rules/management/commands/import_rules_data.py`, run by `_import_classes`): before
writing anything, every one of the 48 XPHB subclasses' granting-level blocks was checked
programmatically against `db/classes.json` - confirming *all 48* have exactly one such block,
always at the granting level, always with at least one nested named feature, and no other level
has this shape. Only then was the transform written: the block's plain-text entries become
`Subclass.description` (a new field - see the [Model status](#model-status) table), and its
nested named entries are promoted to ordinary top-level `{name, entries}` blocks grouped by
level, same as every other level already had (this grouping step is now also how those levels
become `Feature` rows directly - see Issue 2). This also dropped `Effect` from 2142 to 2094
rows - the 48 removed rows are all `{@i ...}` italic-formatting tags that lived in the flavor
text, not real feature text, so they were never a real mechanical effect to begin with; not a
regression.

#### Issue 2: `SubclassLevel.features` duplicated data already in `Feature`

**The problem**: once Issue 1 was fixed, `SubclassLevel.features` held exactly the same
`{name, entries}` data, per level, that the `Feature` rows (FK'd back via `subclass_level`) also
held - two copies of the same information with no independent reason to exist. This is
different from `Class.features`/`Species.entries`/`Feat.entries`, which are each the source's
*own* natural field (kept verbatim on purpose, per `Feature`'s docstring, since `Feature` is an
additive index over them, not their replacement) - `SubclassLevel` isn't a source-native field
at all, it was *built* by this project's own import step purely to group features by level, so
storing that same grouping twice, once as a JSON blob and once as linked rows, was pure
redundancy from day one, not a deliberate tradeoff.

**The fix**: removed `SubclassLevel.features` entirely (migration
`0004_remove_subclasslevel_features`). `_import_classes` now creates the `Feature` rows for a
subclass directly - right where it already computes each level's features via
`_split_subclass_features()` - instead of `_import_features()` re-deriving them later from a
stored JSON field. Anything that displayed a subclass's features now reads `Feature` rows via
`subclass_level.feature_rows` instead (`render_subclasses()` in
`apps/frontend/entries_render.py`) - and since `Feature`'s default ordering is alphabetical by
name (correct for the plain `Feature` listing), that query is given an explicit
`.order_by("pk")` to preserve the source's presentation order instead (verified against Cleric's
Life Domain, whose real order - "Life Domain Spells", "Disciple of Life", "Preserve Life" - is
*not* alphabetical, so this was checked, not assumed).

#### Issue 3: two rendering assumptions broke on `db/handbook.json`'s edge cases

`apps/frontend/entries_render.py`'s generic renderer was built against `db/{classes,species,
backgrounds,feats,spells,rules}.json`, and every assumption in it had been checked against
*those* files - but `db/handbook.json` (the player's-handbook chapter text, added later, far
larger and more varied than any single catalog entry) exercised two shapes nothing before it
had:

- **`{@area ...}` tags got the wrong display text.** `_tag_display_text()`'s "3+ segments ->
  use the last one" rule was written for tags like `{@variantrule Cover|XPHB|Total Cover}`,
  where the last segment is a genuine display override. `{@area ability checks|020|x}` is a
  different tag with the same segment count but a different convention (first segment is the
  text; the rest are an internal target id and a literal page-number placeholder, `"x"`, that
  5etools' own renderer would normally resolve) - so text like "three kinds: ability checks,
  saving throws, and attack rolls" rendered as "three kinds: x, x, and x" instead. Fixed by
  giving `area` the same first-segment rule as `filter` (verified: all 63 `{@area ...}`
  occurrences in `db/handbook.json` end in that literal `"x"`, and the tag doesn't appear in any
  other `db/*.json` file).
- **A list whose `items` held something other than a plain item silently rendered empty.**
  `_render_list_item()` assumed every list item was either a bare string or a `{name, entry}`
  dict - true everywhere else in `db/`, but one handbook list (D20 Tests' "Add Modifiers" step)
  nests a whole second `list` directly inside another list's `items` array, not wrapped in an
  `item`. That dict has neither `name` nor `entry` nor `entries`, so it rendered as an empty
  `<li></li>` - list item 3 of 4 just vanished. Fixed by delegating to the general dict renderer
  whenever a list item is itself a typed node other than `"item"` (verified: this is the only
  such occurrence across every `db/*.json` file, but the fix isn't a special case for that one
  list - the same delegation would handle a table, an inset, or anything else nested the same
  way).

Neither of these was visible in a row count either - the data imported "successfully" both
times; the bug was purely in how it was displayed, for one specific passage out of a very large
document. That's the tell for this category: not "is the row count right" but "read enough of
the actual rendered content, not just the first paragraph of it, to notice something reads
wrong."

#### Issue 4: `Class.features` duplicated data already in `Feature` (same as Issue 2, one model over)

**The problem**: identical to Issue 2, just on `Class`/`ClassLevel` instead of `Subclass`/
`SubclassLevel` - `Class.features` (the source's own raw `{level, name, entries}` list) and the
`Feature` rows built from it held the same per-level feature text twice, and `ClassLevel` (like
`SubclassLevel`, built by this project purely to group levels, not a source-native field) had no
reason to exist as a bare level marker when it could instead be what `Feature` rows link to.

**The fix**: removed `Class.features`; `Feature` gained a `class_level` FK (replacing a `klass`
FK + a separate `level` field, which became just as redundant as `Class.features` once a
`class_level` FK existed - `class_level.level` already gives the level, so keeping a second copy
of it on every `Feature` row would have been the same mistake at smaller scale). `_import_classes`
now builds `ClassLevel` rows first, then creates each level's `Feature` rows FK'd to the matching
one - the exact same shape `_split_subclass_features()` already established for subclasses,
applied consistently one model over.

**A sharper lesson from this one - orphaned rows on schema change, not just on import**: dropping
`Feature.klass` (a migration - `manage.py migrate`, not `import_rules_data`) doesn't delete the
`Feature` rows that only had `klass` set; it just drops the column and leaves the rows behind,
now with every FK null. `_delete_existing()` (the first step of every `import_rules_data` run)
deletes `Feature` rows only by *cascading* from `Class`/`Species`/`Feat` - which does nothing for
rows a schema change already orphaned, since they don't reference any surviving parent to cascade
from. Re-running the import after this migration produced 925 `Feature` rows instead of the
correct 665 - 260 stale pre-migration rows (all-null FKs) sitting alongside 260 freshly correct
ones - caught by cross-checking the post-import count against an independent recount from the raw
JSON (the same discipline as every issue above), not by anything erroring. Fixed two ways: a
one-off cleanup of the existing orphans, and `_delete_existing()` now deletes `Feature` directly
and explicitly rather than relying on cascade, so a *future* FK restructuring can't repeat this -
worth remembering for `Effect`/`Proficiency`/`ChoiceDefinition` too, if any of their parent FKs
are ever similarly restructured.

#### Issue 5: `Skill.ability`/`Class.primaryAbility`/`Class.savingThrows` were free text instead of links

**The problem**: three more free-text fields that were really references to a fixed, tiny set of
six values (the ability scores) that had never been modeled at all. `Skill.ability` held a bare
string ("Strength"); `Class.savingThrows` held a comma-separated pair of the same; `Class.
primaryAbility` was the trickiest of the three - sometimes one ability ("Wisdom"), sometimes two
joined by "or" (Fighter: Strength *or* Dexterity - a real build choice) or "and" (Monk: Dexterity
*and* Wisdom - both matter, for different things). None of these are the same kind of bug as
Issues 1/2/4 - nothing was duplicated or mis-grouped, these fields simply predated `Ability`
existing as a model at all.

**The fix**: added `Ability` (id/name/description), sourced from `db/handbook.json`'s own
"Ability Descriptions" table (Chapter 1 → The Six Abilities) rather than hand-written, since that
table already gives exactly this data - the same "check whether the source already has it before
typing it in by hand" instinct as the `CLASS_SHORT_DESCRIPTIONS` hand-written blurbs earlier,
just landing on the opposite answer this time. `Skill.ability` became a plain FK.
`Class.saving_throw_abilities` became a M2M (the source pair always means "both apply", no
ambiguity to preserve). `Class.primary_abilities` also became a M2M, but paired with a
`primary_ability_conjunction` field ("", "and", or "or") so the choice-vs-both-matter distinction
survives instead of collapsing into an indistinguishable set - verified all 12 classes'
`primaryAbility` strings match one of exactly three shapes (bare name, " or "-joined pair,
" and "-joined pair) before relying on that parse. Word order within a pair isn't preserved
(`Ability.objects.all()` orders alphabetically), but nothing is lost by that - "Strength or
Dexterity" and "Dexterity or Strength" mean the same thing.

**A new kind of gotcha, worth remembering for the next FK-ification**: converting an existing
free-text column to a FK in one migration fails outright on Postgres if any current row's value
doesn't match a target-table id - which it never will here, since the target table (`Ability`)
is *created by that same migration* and starts empty. Since this data is fully disposable
(`import_rules_data` rebuilds it right after migrating, same as every model in this project), the
fix is to clear the column's table before the `AlterField`, via `migrations.RunSQL("DELETE FROM
rules_skill;", ...)` - but that alone still isn't enough: Postgres also refused to add the new FK
constraint's index in the *same transaction* as that `DELETE`
("cannot CREATE INDEX ... because it has pending trigger events" - a deferred FK-check trigger
from the delete still outstanding). Setting `atomic = False` on that migration (so each operation
commits on its own instead of one migration-wide transaction) resolved it. Neither step showed up
in `makemigrations`' auto-generated output - both were only found by actually *running* `migrate`
against real data and reading the error, not by inspecting the generated migration file.

#### Issue 6: a `classFeature` sub-heading became a sibling `Feature` instead of a nested one

**The problem**: same underlying mistake as Issue 1 ("one feature's sub-details treated as
several features"), but the other way around, and via a different source shape. A `classFeature`
entry can point at another one via a `{"type": "refClassFeature", "classFeature": "..."}` node
buried in its own `entries` (already handled - see `_walk_feature_pointers()` - for a *genuine*
sibling feature, e.g. Cleric's Divine Order choosing between Protector/Thaumaturge, each of which
rightly gets its own `Feature` row). But 12 of these pointers (across Cleric/Druid/Monk) target a
`classFeature` marked with a `header` field - 5etools' own nesting-depth marker for "this is a
sub-entry of whatever points at it, not standalone" - e.g. Monk's Martial Arts embedding Bonus
Unarmed Strike/Martial Arts Die/Dexterous Attacks, or Cleric's Channel Divinity embedding Divine
Spark/Turn Undead, exactly how the printed book presents them. Importing every pointer target as
its own `Feature` row regardless split each of these into extra top-level Monk/Cleric/Druid
features standing alongside their real parent, instead of nested content within it - the same
*kind* of wrong-shape bug as Issue 1, just at the class level and via a pointer rather than a
bundled block.

**How it was caught**: reported directly - "Bonus Unarmed Strike, Martial Arts Die, and Dexterous
Attacks are all subheadings of Martial Arts... these three are listed as separate features"
- not visible from a row count (283 `classFeature` rows imported "successfully" either way), same
non-tell as Issue 1.

**The fix** (`_inline_header_class_features()` and the `classFeature` loop in `_import_classes`,
`apps/rules/management/commands/import_rules_data.py`): a pointer target with `header` set no
longer gets its own `Feature` row; instead, wherever a pointer to it is found (anywhere in a
`Feature`'s own `entries`, not just at the top level - Druid's Elemental Fury wraps its two
pointers inside an extra `options` node), it's replaced in place with that target's own name/
entries inlined as a named nested block (rendered as a sub-heading `<h3>` inside the parent's
card - `entries_render.py` already had this exact shape covered, see `.entry-card > h3`'s own
comment in `detail.html`, since a Wizard's Spellcasting feature nests Cantrips/Spellbook the same
way natively in the source). Verified against all 12 `header`-marked rows (not just Monk's) before
relying on `header` as the general signal, and specifically *not* applied to `subclassFeature`
(229 of 309 rows there have `header` set, but for a different, already-correct reason - see the
model status table's `Feature` row).

`db/it/features.json` needed the matching structural change: the 12 sub-features' Italian text
moved from their own now-gone top-level keys into their parent's `entries` overlay, at the same
position the English inlining puts them (`overlay_translation()` walks list/dict positions in
parallel, so the two have to line up) - done by hand, once, preserving the existing official
Italian text verbatim rather than re-translating it.

#### The general lesson, for next time

A model being "Defined" (mapped field-for-field) doesn't mean the source's own grouping is
semantically correct, or that nothing downstream of it is redundant:

- **Wrong grouping** (Issues 1 and 6): 5etools' JSON is authored for its own renderer, not for
  this schema, and a block that looks like "several features" can actually be "one feature with
  sub-details" (Issue 6, a `header`-marked pointer target) - or the other way around, "one
  feature with sub-details" that's actually "several features that got flavor text stapled to the
  first one" (Issue 1). Same wrong-shape failure mode both ways: it surfaces as something
  structurally *off* on a rendered page (not "missing data" but "correct data, wrong shape"), and
  a fix for one direction is worth checking for the other, not assumed to be the only shape 5etools
  uses for "these belong together."
- **Redundant storage** (Issues 2 and 4): a field that exists only because *this project* built
  it (not a source-native field kept verbatim on purpose) is worth asking "does something else
  already hold this same data via a queryable relation?" - if so, the JSON copy is dead weight,
  not a deliberate tradeoff. Once found in `SubclassLevel`, it was worth deliberately checking
  `ClassLevel` for the same thing rather than assuming it was one-off - it was.
- **Untested rendering assumptions** (Issue 3): the generic renderer's rules (which tag
  convention applies, what shape a list item has) were each derived from - and only checked
  against - the handful of `db/*.json` files that existed when they were written. A new file
  large and varied enough (a whole handbook chapter, not one catalog entry) can exercise a shape
  none of those checks ever saw, and the failure is silent (no error, no missing row) - only
  visible by actually reading the rendered output.
- **Orphaned rows on schema change** (Issue 4's second half): removing a FK column doesn't
  delete the rows that only had *that* FK set - it just drops the column and leaves them behind,
  parentless. `_delete_existing()`'s cascade-from-parent-catalogs approach silently doesn't reach
  those. Worth remembering for `Effect`/`Proficiency`/`ChoiceDefinition` too, if their parent FKs
  are ever restructured the same way.
- **Never-modeled references, not duplication or bad grouping** (Issue 5): a fixed, tiny,
  named set of values (the six abilities) hiding as free text in *three different fields* across
  *two different models* - a different smell than Issues 1/2/4 (nothing was duplicated; `Ability`
  simply never existed as a model), and one worth the same "does this string actually name a
  thing that should be its own row?" question, not just "is this JSON shaped weirdly" or "is
  this data duplicated elsewhere."
- **Converting free text to a FK, on data that already exists** (Issue 5's second half): unlike
  every earlier fix, this one hit real migration mechanics, not import-script logic - Postgres
  rejects the new FK constraint outright if existing rows don't satisfy it (guaranteed here,
  since the target table is created by that same migration and starts empty), and rejects
  certain DDL sharing a transaction with a same-table `DELETE` right before it. Both were only
  visible by actually running `migrate` against real data, not from `makemigrations`' output or
  from reading the generated migration file.

Either way, the same discipline applies: don't fix the one example that prompted the question -
*verify the fix's assumption against every occurrence in `db/`* (a small Python script over
`db/*.json`, not just one subclass or one passage) before changing the import command or the
renderer, and *re-check the actual row counts after*, independently recomputed, not just "did it
run without an error" - the way every issue above was checked against all 48 subclasses, or all
63 tags, or all 12 classes' `primaryAbility` shapes, or a fresh count from raw JSON, rather than
just the one Monk/Cleric/D20-Tests/`Class.features` example that surfaced each. `Species`,
`Feat`, and `OptionalFeature` all have similarly-shaped `{name, entries}` source lists and
haven't been audited for the Issue 1/2/4 patterns, and free-text fields elsewhere (`Feat.
prerequisite`, `Background.ability_scores`, ...) haven't been checked for the Issue 5 pattern -
they're plausible places to look next.

### `apps/rules/` — static game content

Read-only reference data: classes, species, backgrounds, feats, equipment, spells, and the rules
that tie them together.

**Models** (`apps/rules/models/`, one file per model) are populated from the XPHB (2024 Player's
Handbook) data dumped in [db/](db/) — see [Model status](#model-status) below for exactly what's
defined, what isn't, and why. Fields deliberately dropped everywhere: `image`/`gallery` (art
assets) and `otherVersions` (cross-references to non-XPHB printings — we only use source XPHB).

| Model | Will represent |
|---|---|
| `Rule` | A named rule/keyword (e.g. Grappling, Cover) |
| `Feature` | A discrete class/subclass/species/feat feature grant |
| `Effect` | A mechanical effect attached to a `Feature` |
| `ChoiceDefinition` | A choice a player must make (e.g. "pick 2 skills") |
| `Species` | A player species (e.g. Elf, Dwarf) |
| `Background` | A character background (e.g. Soldier, Sage) |
| `BackgroundStartingEquipmentOption` | One item (or gold grant) in a `Background`'s starting-equipment choice |
| `Feat` | A feat (e.g. Alert, Tough) |
| `Class` | A character class (e.g. Fighter, Wizard) |
| `ClassLevel` | The per-level progression row for a `Class` |
| `ClassStartingEquipmentOption` | One item (or gold grant) in a `Class`'s starting-equipment choice |
| `Subclass` | A subclass/archetype of a `Class` |
| `SubclassLevel` | The per-level progression row for a `Subclass` |
| `Equipment` | An item of equipment (weapon, armor, gear, tool, instrument, ...) |
| `EquipmentType` | A category of `Equipment` (e.g. Melee Weapon, Heavy Armor) |
| `EquipmentGroup` | A named category of interchangeable `Equipment` (e.g. Arcane Focus) |
| `EquipmentPackContent` | One item stack inside an equipment pack (e.g. Burglar's Pack) |
| `EquipmentProperty` | A property attached to `Equipment` (e.g. Finesse) |
| `Mastery` | A weapon mastery property |
| `Skill` | A skill (e.g. Athletics, Perception) |
| `Ability` | One of the six core ability scores (Strength, Dexterity, ...) |
| `Sense` | A special sense (e.g. Darkvision) |
| `Condition` | A condition (Blinded, ...) or glossary status (Bloodied, ...) with its rules text |
| `Proficiency` | A proficiency category (weapon/armor/tool/skill) granted by a `Class` or `Background` |
| `Language` | A language (e.g. Common, Elvish) |
| `Spell` | A spell definition |
| `OptionalFeature` | An optional class feature a player can pick (Eldritch Invocation, Maneuver, Metamagic) |
| `HandbookChapter` | A chapter of the player's handbook ("Playing the Game", "Spells", ...) - the heading its sections are grouped under |
| `HandbookSection` | A named topic of the player's handbook (rules text, not catalog data) |

**Services** (`apps/rules/services/`, one file per resource domain): `class_.py`, `subclass.py`,
`species.py`, `background.py`, `feat.py`, `feature.py`, `equipment.py`, `skill.py`, `sense.py`,
`language.py`, `optional_feature.py`, `proficiency.py`, `spell.py`, `rule.py` — plain functions
returning querysets/instances, no HTTP concerns. Path-validity checks (e.g. `list_class_levels`
404ing if the class doesn't exist) live here, not in the views.

### `apps/campaigns/` — who plays with whom

A **campaign** is the one scope of the app's private content: its characters and its Logbook. There
are no groups above it. Models (`models/`, one file per model): `Campaign` (`name`, `description`,
a secret `join_code` the DM can switch off or replace), `CampaignMembership` (`role` is `dm` or
`player`; the database allows exactly **one DM per campaign**) and `CampaignInvite` (an e-mail,
stored lower-cased, open for about six months; accepting or declining closes it). Services
(`services/`): `membership.py` (**the one place that answers "who may see/manage what"**:
`campaigns_for`, `is_member`, `can_manage`, `resolve_current`; administrators from
`ADMIN_ACCOUNTS` are treated as members of, and DMs in, every campaign), `lifecycle.py` (create a
campaign - its creator becomes the DM -, rename, hand the DM role over, join link, join by code) and
`invites.py` (invite by e-mail, 20 per user per hour, match against the signed-in account's
verified e-mail, accept/decline/withdraw).

Everything that touches characters lives one layer up, in
`characters/services/campaign_ops.py`: **copy** a character into any campaign you belong to
(deep copy of the row and everything hanging off it - play state, inventory with its containers,
money, portrait and pictures; the copy is yours; Logbook entries are never copied), **transfer** a
character to another campaign (its owner or the DM; the owner has to be a member there too, and the
Logbook entries stay behind), **leave / remove a member** (their characters in that campaign are
deleted; the DM cannot leave before handing the role on) and delete an empty campaign.

The first migration puts all existing accounts, characters and Logbook entries into the campaign
**Obelisco infranto**, whose DM is `rikyfr95@gmail.com`. Signing in is still gated by Cloudflare
Access, which is managed by hand (people ask `scimone.mail@gmail.com`); a campaign invite only decides
what the account sees once it is in.

### `apps/characters/` — persisted character state

The actual player characters, each in one campaign (`Character.campaign`, `PROTECT`). Who sees and
changes one is in `services/access.py` (see **Access** below).

**Models** (`apps/characters/models/`, one file per model) now have real fields — there's no
external data source to import here (this is app-generated state, not static content), so
"defined" instead means: real fields, real FKs into `rules`, verified by actually building one
complete level-5 multiclass-ready character through every model and reverse relation at once (a
Human Fighter/Battle Master, exercising every FK — species, background, class, subclass, a
feature, a feat, an optional feature, a language, skill + armor proficiencies, a sense, an
inventory item, currency, a resource — with no constraint violations).

| Model | Represents |
|---|---|
| `Character` | A player character. Ability scores are plain fields (current totals), not a separate one-row-per-ability table — see `CharacterAbilityScoreIncrease` below for why. AC/HP-max-aside/initiative/passive Perception etc. are deliberately *not* fields: they're derived from everything else and belong in `builder.services.derived_stats`, not persisted (a stored value can silently go stale when a feature/item changes; a computed one can't). The play-state the sheet edits is stored, though: `current_hit_points`/`temporary_hit_points`, `inspiration`, `death_save_successes`/`death_save_failures`, and `spell_slots_spent` (`{"<slot level>": n, "pact": n}` - only what is *spent*; the maximum is derived from the class levels, so it can't go stale). Spent Hit Dice live on `CharacterClass.hit_dice_spent`. `portrait` is the uploaded picture (an `ImageField` under `MEDIA_ROOT`, see the character sheet section) |
| `CharacterClass` | A class/subclass + level a `Character` has (one row per class — multiple rows is how multiclassing is represented) |
| `CharacterAbilityScoreIncrease` | Renamed from the doc's `CharacterAbilityScore` — it's one line of ability-score *history* ("+2 Wisdom from Background", "+1 Constitution from an ASI at level 4"), not "the current score" (that's the plain field on `Character`) |
| `CharacterChoice` | A resolved builder choice, keyed by an arbitrary string (e.g. `"fighter.level_8.feat"`) — not FK'd to `rules.ChoiceDefinition`, which only covers ~27 choices reliably parseable from prose; most real choices (subclass, known spells, expertise, invocations, "A or B" starting equipment) have no such catalog row and never will |
| `CharacterFeature` | An automatic `rules.Feature` grant active on a `Character` (Rage, Second Wind, a species trait, ...) |
| `CharacterFeat` | **New** — a `rules.Feat` the player *chose* (background feat, general feat at an ASI level, epic boon). Missing from the original list, and was being wrongly conflated with `CharacterFeature` (automatic grants only) |
| `CharacterOptionalFeature` | **New** — a `rules.OptionalFeature` the player picked (Eldritch Invocation, Maneuver, Metamagic). Missing from the original list because `rules.OptionalFeature` didn't exist yet when it was drafted |
| `CharacterLanguage` | **New** — a `rules.Language` the character knows. Same story as `CharacterOptionalFeature` — `rules.Language` didn't exist yet either |
| `CharacterProficiency` | Armor/weapon/tool/skill/saving-throw proficiency. Not exclusively FK'd to `rules.Proficiency` (that catalog misses species/feat-granted proficiencies entirely) — `category`/`name` are stored directly, with an optional provenance link back to the catalog row when there is one |
| `CharacterSense` | A `rules.Sense` grant with its range in feet (the range varies by source, e.g. a species trait vs. a feat, so it lives on the grant, not on `rules.Sense` itself) |
| `CharacterInventoryItem` | An `Equipment` stack a `Character` owns, with `equipped`/`attuned`/`quantity` |
| `CharacterCustomItem` | **New** - an item the player made up (name, quantity, weight, cost in copper, "trade good or valuable" flag, inventory section, a free-text finer type within it, description, optional weapon/armor stats, a ranged weapon's range, `wearable` and `effects`); sheet-only, see the character sheet section |
| `CustomCatalogItem` | **New** - a campaign's permanent catalog of custom items: every `CharacterCustomItem` added (or edited, or already existing - migration 0029) is also kept here, one entry per name, and is listed (marked *Custom*) in the Add item overlay with Add/Buy (`custom_catalog_add`/`custom_catalog_buy`); shares its fields with `CharacterCustomItem` through the abstract `CustomItemBase` |
| `CharacterCustomFeature` | **New** - a feature the player made up (name, description, `effects`); sheet-only, listed on the Features tab |
| `CharacterCurrency` | The coin purse — a true 1:1 with `Character` (`character` is both the FK and the primary key) |
| `CharacterSpell` | A spell a `Character` knows/has access to, with `prepared`/`always_prepared` flags |
| `CharacterResource` | A limited-use resource (Rage, Sorcery Points, Superiority Dice, ...) with `max_uses`/`current_uses`/`reset_on` |

**Services** (`apps/characters/services/`, one file per domain): `character.py` (CRUD + the
sheet aggregator), `classes.py`, `feats.py`, `features.py`, `languages.py`,
`optional_features.py`, `proficiencies.py`, `senses.py`, `resources.py`, `choices.py`,
`inventory.py`, `currency.py`, `spells.py`, and `play.py` - what the character sheet's owner ticks while playing (HP with temporary-HP absorption, death saves, Hit Dice, spell slots, coins, worn gear, free text, and the items carried: add, buy, count, remove, sell; and the spells added by hand). **This is where spending a resource lives** (the "open design question" this project had): `characters` owns play-state, `rules` stays read-only and `builder` stays creation/leveling. Each function clamps/validates and raises `ValueError` on nonsense. Rests (short/long, which would restore what is spent) are still not implemented.

### `apps/builder/` — character creation/leveling engine

The D&D character engine: what can be chosen, whether a choice is valid, what it grants, and how
leveling up works. It's logic bolted onto a `characters` resource, not a separate top-level
resource, and has no HTTP surface of its own - the frontend calls its services directly. Owns
little to no persistent state of its own; it reads/writes `characters` models by applying `rules`
data.

**Level-1 character creation is implemented** (see [Character creation](#character-creation)
below), and so is **level-up with multiclassing** (see [Levelling up](#levelling-up)). The frontend calls the services directly,
like the World views call `rules`. Builder is an actual rules engine (per-class choice validation,
prerequisite checking, multiclass spell-slot math, ...) and was designed in
[docs/character_creation_plan.md](docs/character_creation_plan.md).

**Services** (`apps/builder/services/`; the ones marked ✅ are implemented, the rest are still the
docstring-only placeholders from the design doc):

| File | Will hold |
|---|---|
| `builder.py` | `BuilderService.get_state(character)` — the central state aggregator the builder is built around |
| `choices.py` | Resolving/validating individual builder choices |
| `validation.py` | Whole-character validation (what's missing/invalid) |
| `prerequisites.py` | Prerequisite checks for feats/features/choices |
| `progression.py` ✅ | Level-up `plan()` / `commit()` - see [Levelling up](#levelling-up) |
| `effects.py` | Applying `rules.Effect` grants onto a character |
| `derived_stats.py` | Computing derived statistics (AC, HP, saves, etc.) |

**Resolvers** (`apps/builder/resolvers/`, currently docstring-only placeholders) — each knows how
one `rules` concept translates into grants on a character: `class_.py`, `species.py`,
`background.py`, `feat.py`, `equipment.py`, `spell.py`, `proficiency.py`.

#### Character creation

Implements the SRD's "Creazione del personaggio" chapter for a level-1 character. The full design,
the data audit (which `rules` data was insufficient and how it was fixed) and the phase-by-phase
progress live in [docs/character_creation_plan.md](docs/character_creation_plan.md); this is the
map of the code.

- **Choices are the source of truth; grants are derived.** Everything the player picks is stored in
  `characters.CharacterChoice` (JSON, dotted keys - the list is in `services/store.py`) plus
  `Character.species/background/alignment` and the starting `CharacterClass`. `services/effects.py`
  `apply()` deletes and rebuilds *every* generated row (proficiencies, features, feats, spells,
  inventory, languages, senses, resources, ability rows) from those choices, so going back and
  changing the background can't leave a stale grant. Only *drafts* (`Character.status ==
  "draft"`) are recomputed; a finished character's rows are its own.
- **`tables.py`** - the chapter's static tables/formulas (standard array and the per-class array,
  point-buy costs, XP, proficiency bonus, hit points, the 1d12 languages, alignments, armor Dex
  caps). They aren't in `db/`, and `rules` tables are wiped by `import_rules_data`, so they are code.
- **`class_spec.py`** - what each class asks for at level 1 that `db/` only states in prose
  (weapon-mastery count, expertise, spellbook size, Divine/Primal Order effects, always-prepared
  spells, level-1 resources, unarmored defense). `tests/test_class_spec.py` fails if the imported
  data stops agreeing with it.
- **`services/feature_resources.py`** - the limited-use species/feat/subclass features that are not
  class-table resources (Breath Weapon, Luck Points, Warding Flare, ...): `FEATURE_RESOURCES` names
  them once, `refresh()` gives a character a `CharacterResource` for each it has (called after
  creation, every level-up and a feat taken on the sheet). `services/land.py` is Circle of the
  Land's land, chosen anew after every Long Rest (`Character.rest_choices`, opened by `play.long_rest`).
- **`resolvers/`** - pure "what does this grant" logic (`class_`, `species`, `background`, `feat`,
  `equipment`, `spell`, `proficiency`, `held`, `abilities`) feeding a `Grants` object.
- **Services** ✅ `store` (`Draft`, `Issue`, `Picker`), `origins` (class/background/species/languages/
  equipment/alignment), `abilities`, `class_choices`, `effects`, `validation`, `creation` (start /
  progress / details / finalize / discard), `derived_stats`. A `Picker` (how many, from which
  candidates, what is selected) is the single description of a choice: the screens render it and
  validation judges it, so they can't disagree.
- **Rules worth knowing**: no picker offers a skill/tool the character already has (D6); the
  ability-score roll is made once per character; a pack is stored as its individual items, each
  row's `parent` pointing at the pack row; **ability scores and skills can be overridden by hand at
  the Review step** (`manual.abilities` / `manual.skills`, applied last, only where they differ from
  what the rules give), whatever class/species/background say.
- **Derived stats** (`derived_stats.compute`) are computed from rows, never stored: AC (armor + Dex
  cap, shield, Barbarian/Monk Unarmored Defense - best single calculation), saves, all skills,
  passive Perception, attacks, spell DC/attack, warnings (untrained armor, Strength requirement).

#### Levelling up

`services/progression.py` (rules that `db/` only states in prose: `progression_spec.py`) advances a
*finished* character one level, from the sheet's owner (`/characters/<id>/levelup/`, the **Level up**
button under the XP bar of the Stats tab - highlighted once the XP reach the next level, available
anyway for milestone tables - and a pill on the owner's row of the Characters list once the XP
allow it). A finished character's rows are its own, so this does not recompute from choices like
the wizard: `plan(character, class_id, values)` reads the rows as they are and returns the
`Plan` (the `Section`s of `Picker`s the level asks for, hit points, the features gained, issues);
`commit()` applies the same `values` in one transaction. The page re-renders on each change (the
wizard's live pattern) and saves nothing until *Level up*.

What a level does: pick the class to advance (a new class needs 13 in the primary ability of the new
class *and* of every class the character has, "and"/"or" per class); hit points (average or a roll,
+ Constitution, + Tough / Dwarven Toughness, + Draconic Resilience; a Constitution raise also
changes the earlier levels); the subclass at its level, with the subclass features, its always-
prepared spells (Domain/Oath/Circle/Patron, the Circle of the Land's land) and a Wizard school's
Savant spells; the class features of the level; the feat or Ability Score Improvement at its
levels (the ASI is a feat: +2 / +1 +1 capped at 20, half feats +1, Epic Boon capped at 30; feat
prerequisites are checked against level, ability scores, armor training and spellcasting; the
feat's own picks - skills, expertise, saving throw, spells, a spellcasting ability - are asked);
the class's own choices (Expertise, Fighting Style, Weapon Mastery, Metamagic, Maneuvers, Eldritch
Invocations - with the level-up swap -, Primal Knowledge, Scholar, Deft Explorer, Student of War,
Lore's skills); spells (cantrips and prepared spells by the class table, the Wizard's two spellbook
spells, a swap for the classes that may, Mystic Arcanum, Eldritch Knight / Arcane Trickster casting
from the subclass's own tables); the limited-use resources (`LEVEL_RESOURCES`: Rage, Channel
Divinity, Action Surge, Indomitable, Focus Points, Sorcery Points, Superiority Dice, ...); and the
Experience Points if they were below the new level. A **multiclass entry** also gives the SRD's
multiclass proficiencies (`MULTICLASS_GAINS`), the class's level-1 features and choices, and
its own Hit Die pool. Spell slots of a multiclass caster combine as the SRD says (the sheet already
did). Not modelled: the subclass choices that are only prose with no row to write (Hunter's
Prey, Blessed Strikes, Rage of the Wilds ... are read in the feature's text), resistances from
feats, swapping Weapon Mastery or Expertise at a rest.

**Rebuilding a levelled character** (`services/rebuild.py`, admins only above level 1; the
**Edit character** item of the sheet's menu). The wizard recomputes a character from its level-1
choices, so a levelled one is taken back to a level-1 draft first (the extra classes, the subclass
and every level-up choice are removed; inventory, coins and Experience Points stay) and its
level-ups, which `progression.commit()` records in `meta.history`, are set aside. The admin changes
whatever they like in the creation screens - everything granted by a changed component simply
disappears, as the rows are rebuilt from the choices - and on *Finish* the levels are replayed
(`/characters/<id>/rebuild/`): a level whose recorded picks still hold is re-applied silently, any
other (a swapped class, a pick that a new species/background made impossible, a new pick) is shown
on the level-up page with the valid picks filled in. The character is complete again after the last
level. Changes made by hand on the sheet (feats added there, prepared-spell swaps, ...) are not
replayed; a character levelled before the history existed has every level asked again; the
multiclass minimums are waived while replaying; the starting equipment step is not asked while
editing, since the inventory is kept.

**Access** (`apps/characters/services/access.py`): every finished character is *visible* to every
member of its campaign (and to administrators), and to nobody else - they get a 404. The character's owner, the
campaign's DM and administrators edit and delete it; only the DM and administrators move Hit Dice
and spell slots by hand and reassign the owner. An unfinished one is its editors' only. `can_view(user,
character, section)` is the single place to later hide sections of a character from other members.

### `apps/frontend/` — PWA shell

Not part of the `rules`/`characters`/`builder` layering above (it's the web UI, not game logic).
A minimal Django app serving server-rendered pages, wired up as an installable PWA via
`django-pwa`.

**Navigation shell** — every page (`templates/frontend/base.html`, extended by the rest) has a
header with a back button (omitted on a menu's root page, see **Navigation model** below), the
current page's title, and one language-toggle button that switches to the *other* language, labeled
with that language's own autonym (e.g. shows "Italiano" while browsing in English). Responsive,
mobile-first CSS with a dark-mode variant; a JS-measured `--app-height` custom property works
around mobile browsers resizing the visible viewport as the address bar shows/hides.

- **Navigation model** (`static/js/navigation.js`, loaded by `base.html`). The pages are
  server-rendered, so the browser's history is one linear list; this script gives each bottom-nav
  menu (Characters / Logbook / Handbook) its own history stack instead, kept in `sessionStorage`
  (entries are `{u: url, p: static parent, y: scroll offset}`):
  - **Back** - the header arrow *and* the phone's back button - goes one step back inside the
    active menu, never into another menu visited on the way. At a menu's root nothing happens
    (root pages - the Handbook home and its category tabs - have no arrow). A deep
    link with an otherwise empty stack falls back to the page's static parent (the arrow's `href`).
    Scroll position is restored on the way back.
  - **The active menu changes only through the bottom nav** (which resumes another menu on the page
    it was left on), not by URL: the Glossary (Handbook) links into `/world/rules/...`, and
    back from there returns to the Glossary. The bottom nav highlights the active menu, not the
    URL prefix.
  - **Tapping the bottom-nav item of the menu you are already in** returns to that menu's root
    (`data-root`; the Handbook's is its home, `/world/`) and resets its stack - so from a class
    page opened earlier, tapping Handbook shows the search home again. Tapping *another* menu resumes
    it where it was left.
  - **Not steps**: World's category tabs, a detail page's `?tab=` tabs, live search and the
    language switch *replace* the current entry (`data-nav="replace"` on the link/form). The
    language form's `next` carries the full path + query + `#fragment`, so switching language
    keeps you on the same tab, search text and scroll position. The account page is transient:
    signing in/out (`data-nav="pop"`) removes it from the history.
  - **Phone back button**: a page cannot cancel a browser back traversal, so every page keeps a
    two-entry history guard of its own (`base`, `top`). Back lands on `base` in the same
    document, `popstate` fires and runs the same `goBack()` as the arrow; at a root the guard is
    re-entered with `history.go(1)`. If a browser skips the script-added entries anyway (Chrome
    does for a page with no user interaction yet) and the traversal reaches another document,
    `arrive()` recognises the `back_forward` navigation type and applies the same rule.
  - `TrackLastSectionUrlMiddleware`/`last_*_url` remain as the bottom nav links' `href`
    fallback (no JS, or a menu with nothing in this session's stack yet).
- **Campaigns** (`campaign_views.py`, `campaign_context.py`, templates under `frontend/campaigns/`): the
  current campaign is kept in the session (`campaign_context.current`; the first one you joined if
  it is gone) and shown as a bar above the Characters and Logbook lists, which lead to
  `/campaigns/`. A user in no campaign sees an explanation there (create one - becoming its DM -, or
  join) instead of characters and Logbook; the World and Handbook stay open. `/campaigns/` lists your
  campaigns, the invitations waiting for your e-mail (accept/decline), "create" and a "join with a
  code or link" box; `/campaigns/<id>/` shows the members (the DM can make another member DM or
  remove one), invitations (any member invites by e-mail, a member can withdraw), the join link
  (`/join/<code>/`; the DM switches it off or replaces it), settings and delete (DM), and Leave
  (with a warning listing the characters that leaving deletes). A character's 3-dot menu has
  **Copy to a campaign** and, for its editors, **Move to another campaign** (`/characters/<id>/move/`).
- `GET /` (`index`) — redirects to **Characters** (`/characters/`); the bottom nav also has
  **Logbook** and **Handbook** (the open-book icon) → `/world/`: the Handbook home, a search box over every
  category at once (rules, backgrounds, classes and subclasses, species, features, spells, equipment;
  `views._global_search()`, live, results grouped by category with jump chips and a "Show more" fold) and,
  until something is typed, a tile per category. Its tab strip (`All` = this home, then **Rules**, the old
  Handbook at `/handbook/`, Backgrounds, ...) is on every category page, each with its own scoped search
  whose empty result offers the global one.
- **Characters** (`character_views.py` for the list and the wizard, `character_sheet.py` for the finished character's page; templates under `frontend/characters/`): `GET /characters/`
  lists every finished character of the current campaign (with its owner) plus the viewer's own
  unfinished ones under "In creation" (the DM and admins see everyone's); the **`+`** button
  (`/characters/new/`, any member of the campaign) asks for a name and starts the wizard at `/characters/<id>/create/<step>/` - steps `background →
  class → species → languages → equipment → abilities → alignment → story → review`, each
  reachable from a progress bar once its prerequisites exist. Progress is saved on every step (the
  draft is a real `Character` row), so leaving and coming back resumes. Finish and Discard use
  `data-nav="root"` so the wizard leaves the Characters history and lands on the list.
  - **Choices open under the picked row.** Class, background and species are pick-one lists in the
    World's card design (shared CSS in `_item_list_style.html`; backgrounds get the same vignette);
    the picked row's own choices - the class's level-1 choices (there is no separate "class
    features" step), a background's tool and feat picks, a species' size/lineage/cantrip/skill -
    open directly under it. A script (`wizard_base.html`) POSTs `action=select` when a row is
    clicked and `action=refresh` when an answer changes what other answers offer (a picker with
    `refresh=True`: skills, Divine/Primal Order, spellbook, lineage), then swaps `.wiz` with the
    server's page - no "Save and continue" needed to see them. Without JS the button does the same
    through a full page load.
  - **Catalog pickers are cards.** A picker of spells, tools, weapons, feats, invocations or skills
    (`Picker.kind`) renders in the World's list design - school/feat-category icon, name, the same
    properties line - with a **Read** button that unfolds the description, fetched lazily from
    `GET /characters/describe/<kind>/<id>/` (spell facts + entries, tool/weapon facts with
    properties and Mastery, ...). Other pickers stay a select/checkbox group.
  - **Order-independent answers**: a later answer can invalidate an earlier pick (a background that
    already grants a skill picked for the class); `services/prune.py` drops such picks on every
    recompute, and the step shows the choice as still to do.
  - **Background story** (`story`) is one free-text field (`Character.backstory`) with the SRD's
    six "past and present" questions above it as a writing guide.
  - **The character sheet** (`GET /characters/<id>/`, `character_sheet.py`, templates under
    `frontend/characters/sheet/`, script `static/js/character_sheet.js`). One page holding every tab;
    `?tab=stats|abilities|features|spellbook|inventory|proficiencies|biography` only picks the one shown
    first (Stats when there is none; the script switches tabs without reloading and keeps the query string current, so a
    reload or a language switch returns to it). Each tab has a `_<tab>()` function that turns rows
    plus `derived_stats.compute()` into plain dicts, so the templates hold no logic. The top block
    never scrolls (only the panels below it do), so it is sticky without `position: sticky` - it
    holds only the tab strip; who the character is (portrait, name, level, class, species,
    background, size) lives in the Biography tab, not a page header (see *Biography* below).
    - *Stats* (the default tab): a dashboard of cards on a 12-column grid, top to bottom: Experience
      Points (the field, the next level's threshold and a progress bar; changing it redraws the page
      so the bar follows); Armor Class (an emblem, with a **Shield** pill that equips/unequips the
      character's shield, so AC and the Inventory follow), Initiative and Speed; Passive Perception
      and Heroic Inspiration (a tile that toggles); **Hit Points**, the centrepiece (a big editable
      number, big -/+ buttons - damage eats temporary HP first - the Temp HP field and a bar); and,
      right under it and on one line, **Hit Dice** (one pip per die, the Spellbook's slot pips: tap
      a full one to spend it, an empty one to recover it) and Death Saves (3 + 3 boxes; on a phone
      their labels shrink to a tick and a cross to fit). Everything is read-only for anyone but the
      owner (no controls are rendered, and the endpoint answers 403).
    - *Gallery* (Biography tab): the extra pictures are one swipeable row of small thumbnails (plus a
      "+" tile for the owner), so any number of them takes a single line. Tapping one opens a
      full-screen viewer (`character_sheet.js`, built on `<body>`): a scroll-snap track swiped
      sideways, a counter, arrow keys / buttons on a desktop, Esc or a tap on the dark area to
      close, and - for the owner - a trash button removing the picture on screen.
    - *Portrait* (in the Biography tab): the owner taps the picture (a "+" badge marks it) to choose
      a file, and an "x" badge removes it. `POST /characters/<id>/portrait/` takes the multipart
      `file` (or `remove=1`);
      `GET` of the same URL serves it to anyone who may see the character (`?v=<file name>` in the
      page's `<img>` busts the cache, because every upload gets a new name). The upload is decoded,
      turned upright, shrunk to fit 600 x 800 and stored again as a WebP under `MEDIA_ROOT`
      (`characters.services.portrait`): a JPEG/PNG/WebP/GIF of at most 10 MB is accepted, anything
      else is refused, and nothing the user sent is ever served as it came. It is
      `Character.portrait`, an `ImageField` (needs Pillow). `MEDIA_ROOT` is `media/` (git- and
      docker-ignored, or `DJANGO_MEDIA_ROOT`); docker-compose bind-mounts `./media` into the
      container so a redeploy keeps the pictures. There is no `MEDIA_URL`: files go through the view.
    - *Abilities*: the proficiency bonus and six boxes in a 2 x 3 grid (modifier, score, save with a
      proficiency pip) that stay in view, then the "Skills" heading with the pip legend (not
      proficient / proficient / expertise) next to it (also fixed, on the page colour), with the
      skills (none / proficient / expertise pips) scrolling beneath it.
    - *Features*: species traits, class and subclass features, feats, and options (invocations,
      maneuvers...) as the World Features list's own rows (search box, Type pills, bookmarks; a row
      opens its World page). The fixed block also carries a toolbar with the feature count and, for
      the owner, an **Add feature** button - shown even for a character with none. A feature the
      player added by hand has a trash button on its row (what the builder granted cannot be removed).
    - *Add feature* (`GET /characters/<id>/features/`, owner only, a third full-screen overlay loaded
      on first use, like *Add spell*): the whole catalog - class, subclass and species features,
      feats and options, minus the Ability Score Improvement every class repeats - as one list with
      the World's search box, a Type pill and, once one that fits is picked, Class / Species filter
      buttons; rows Add (or show "Added") and unfold their description. `feature_add` /
      `feature_remove` take `feature=<kind>:<id>` (`feature`, `feat` or `option`); an added row is a
      `CharacterFeature` / `CharacterFeat` / `CharacterOptionalFeature` with `source="sheet"`
      (`play.add_feature`, which is also how `play.remove_feature` knows what may be removed).
    - *Spellbook*: a fixed block (`.cs-sticky`) holds the casting ability select (one entry per
      casting source) with Mod/DC/Atk, a toolbar (the spell count and, for the owner, an **Add spell**
      button - shown even for a character with no spells), **and the World's own search box and filter buttons**
      (`_search_form.html`, same look) over the character's spells, filtered in the browser with the
      filters limited to what those spells use. Below it scroll the slot pips (read-only for players:
      casting a spell spends a slot and a rest recovers them; only the campaign's DM or an admin taps a pip
      by hand, as with Hit Dice - the `slots` action answers 403 to anyone else; Pact Magic separately; a multiclass caster gets the SRD's
      combined table) and the spells; a row unfolds the spell. A spell the player added by hand has a
      **Remove** button in its unfolded row (spells a class, species or feat gave cannot be removed).
    - *Add spell* (`GET /characters/<id>/spells/`, owner only, a second full-screen overlay loaded on
      first use, like *Add item*): every spell as a list in the World's list design with **the
      World's own search box and filter buttons** (Level, Class, School, Range, Casting Time, Saving
      Throw), each row with an Add pill (the spells the character has are marked "Added"; the sheet
      stays open, so several can be added) and a chevron for the description. An added spell is a
      `CharacterSpell` with `prepared=True` and `source="sheet"` (`play.add_spell`, which is also how
      `play.remove_spell` knows what may be removed).
      Spellbook rows have a **Prepare / Prepared** pill (`play.set_spell_prepared`, per the SRD's
      "Preparing Spells"): level 1+ only, always-prepared spells are fixed and don't count, a
      Wizard prepares from the spellbook only, and a class can't exceed its table's prepared
      number. A line per class shows `Prepared n/max` and the SRD's "Spell Preparation by Class"
      rule (when/how many may change - shown, not enforced). Bookmarking exists in the World
      lists only, not on the character sheet.
    - *Inventory*: a fixed top part with the coin pouch (copper/silver/gold/platinum, electrum only
      if owned; editable; the owner's coin discs are "+" buttons that open an *Add money* dialog with
      quick +1/+5/+10/+50/+100 amounts - action `coin_add`; the **Transfer** dialog hands over coins too,
      alongside or instead of items - `coins` in `item_transfer`, `play.transfer_items`), the carried weight and an **Add item** button, then Weapons / Armor /
      Tools / Misc as one list in the Features/Spellbook row style: name, one detail line (damage
      or AC, weight, cost, attunement, and "from <pack>") and a chevron on the right that unfolds
      the description under the row. **Packs are not listed**: their contents are, as ordinary items
      saying which pack they came from (the pack row stays in the database as the parent, and is
      deleted by `play.remove_item` once its last item is gone). Weapons and armor have an Equip
      pill just left of the chevron (wearing body armor takes off the armor already worn); a
      sellable item also gets a small round quick-**Sell** button there (confirms the price first,
      then sells one - `play.sell_item` again; a stack cheap enough that one unit alone would round
      down to nothing, a torch, sells the *whole* stack instead - `_item_card`'s `quick_sell`).
      An unfolded item (for the owner) still has its own
      quantity editor (-/+ or type), **Sell** buttons (one/all) and **Remove** besides. Selling pays
      half the cost (rounded down) into the purse - trade goods and valuables their full value
      (`play.sale_price`; the catalog has none, so that applies to custom items flagged "trade good
      or valuable") - and an item with no cost cannot be sold. The unfolded rows stay open across
      the redraw an action causes. There is no rarity: every catalog item's `rarity` is `none` in
      `db/`.
    - *Add item* (`GET /characters/<id>/items/`, owner only, loaded into a full-screen overlay the
      first time): a sticky coin purse (read-only, the same pouch as the Inventory tab's, kept live
      by the same `data-bind`s) on top, then the whole catalog as a list in the World's list design
      with **the World's own search box**, a row of **pills for the main type** (All / Weapons /
      Armor / Tools / Misc Items - the same sections the Inventory uses) and, only once a pill other
      than All is picked, the filter buttons that mean something for it: Type for each, plus
      Category, Properties and Mastery for the weapons (a `filter` with `only` in
      `_search_form.html`; the filters of a pill that is left are cleared; everything is filtered in
      the browser), a **Quantity** box that Add and Buy follow (bulk add), an always-visible **Set** filter over every
      kind of gear (Adventuring Gear, Ammunition, ...), each row with an Add pill (adds one for free, onto the loose stack of the same
      item if there is one), a **Buy** pill beside it when the item has a price (pays for it out of
      the purse - `play.buy_item` - after a confirmation with the price and what will be left; that
      arithmetic runs in `character_sheet.js` against the live purse, not a string rendered once at
      load time, because this overlay is fetched once and never re-fetched, so a static "you'll have
      X left" could go stale after an earlier buy), and a chevron for the description; and a
      **Custom item** tab (name, category, a free-text finer type within it - e.g. "Light Armor",
      "Potion" - purely a label for the item's detail line, no rules attached, quantity, weight,
      cost in gp, "trade good or valuable", description - added for free regardless of that cost
      field). On the Italian site the weight is
      typed in kilograms. Custom items are `characters.CharacterCustomItem` rows (a separate model:
      the catalog is `rules` data, read-only and wiped by `import_rules_data`, so they cannot be
      `Equipment` rows). They are listed, counted, weighed and sold, and **can be edited afterwards** (an
      *Edit item* page of its own, `?edit=1` on the item's page, action `custom_edit`, which shows only the fields of the item's category - an armor has no weapon fields). A weapon with damage dice (plus
      damage type, optional two-handed/Versatile damage, Finesse / Two-Handed / Ranged, and for a ranged weapon its normal/long range, stored in feet as `"80/320"` like the catalog's) or armor with a kind
      and AC (light/medium/heavy/shield, Strength requirement, stealth disadvantage) can be **equipped** like
      catalog gear: `derived_stats` counts it for Armor Class and the attack list, and it shares the
      armor/shield slots with catalog pieces (`play.set_equipped(..., kind="custom")`). Any other item can be **equipped** too
      once it is marked *Can be equipped* or carries **effects** (`play.CUSTOM_WORN`, no slot).
      *Effects* (`characters/custom_effects.py`; a JSON list on `CharacterCustomItem.effects` and
      `CharacterCustomFeature.effects`, edited with `static/js/item_form.js`) are `{"target", "value"}`
      pairs that `derived_stats.compute()` applies - while the item is equipped, or always for a
      feature: Armor Class, Speed, Initiative, Passive Perception, every attack/damage roll, spell save DC /
      attack, a weapon's own attack/damage (a +1 sword), saves and skills (a bonus, all of them, or
      proficiency / expertise), and ability scores (a bonus, or "at least" - Gauntlets of Ogre Power).
      Not covered: maximum hit points, resistances, senses. A custom item or feature can also
      grant **spells** (`spells`, a JSON list of spell ids, edited with the search-and-chips picker of
      `_spells_editor.html`): `play.sync_custom_spells` keeps them on the sheet as always-prepared
      `CharacterSpell` rows (`source="custom:item:<pk>"` / `"custom:feature:<pk>"`) - a feature's always,
      an item's only while it is worn - and removes them when the item is taken off, edited or removed;
      a spell the character already has from anywhere else is never doubled or taken away. **Custom features** are added from the
      *Custom feature* tab of the Add feature overlay (`custom_feature_add`), listed on the Features tab as
      *Custom* rows, and have a page of their own to edit or remove
      (`/characters/<id>/features/custom/<id>/`, `custom_feature_edit` / `custom_feature_remove`).
      Like the rest of the sheet's play-state, they are not exposed over any API. This overlay (and *Add
      spell*'s) covers the page's own header, so each carries its own language switch; switching
      language there is a real page reload (`?overlay=item|spell`, set by `character_sheet.js` the
      moment the overlay opens and read back on load), so it lands you back in the overlay rather
      than dropping you back on the sheet as if you had backed out of it.
      **Transfer** (Inventory toolbar, owner only, shown when the campaign has another finished character):
      a dialog to tick items and quantities and pick the receiving character, then a confirmation;
      `play.transfer_items` moves them (catalog gear merges into the loose stack on the other sheet, a custom item
      arrives as an unworn copy; a worn item is simply no longer worn).
    - *Proficiencies*: armor proficiencies, weapon proficiencies, weapon masteries, tool
      proficiencies (artisan's tools and the other tools together), gaming sets, musical
      instruments and languages. A weapon grant is spelled out as the weapons it really
      covers ("martial weapons with the Light property" lists exactly those), through the same
      `WeaponProficiency` rules `derived_stats` uses. Masteries, tools, weapons and armor open their
      description in a panel under their group.
    - *Biography*: who the character is, moved here from the old header - the portrait on the left
      (see *Portrait* above) and, on the right, properties: the editable name, the Level badge
      (another account's sheet says "by <owner>" instead), the class (with level and subclass; a
      multiclass lists each, `Fighter 1 / Wizard 2`), and species/background/size/alignment as small
      labelled facts (the species/background links go to the World pages). Below that, the backstory
      (editable in place by the owner, saved when the field loses focus). `Character.appearance`/
      `notes` still exist but the sheet does not show them.
    A panel is a fixed part (`.cs-sticky`: the ability boxes, the casting numbers + search + filters,
    the coin pouch) above its own scrolling part (`.cs-scroll`). The fixed part has the tab strip's
    colour (and the line between them goes), so it reads as part of the menu. Nothing is `position: sticky` - an
    earlier version was, and jittered while scrolling on phones - the fixed part just isn't inside
    the scroller.
    Descriptions come from `GET /characters/describe/<kind>/<id>/`, the wizard's endpoint, which now
    also serves `feature` (a `rules.Feature`) and `mastery`.
  - **`POST /characters/<id>/act/`** is the one endpoint the sheet posts to (form fields `action` +
    parameters; owner only, completed characters only). Actions: `name`, `xp`, `hp_delta`, `hp_set`,
    `temp_hp`, `death_toggle`, `inspiration`, `hit_dice`, `slots`, `coin`, `coin_add`, `equip`, `text` (backstory only),
    `item_add`, `item_buy`, `custom_add`, `custom_catalog_add`, `custom_catalog_buy`, `item_transfer`, `custom_edit`, `item_qty`, `item_remove`, `item_sell`, `spell_add`, `spell_remove`, `feature_add`, `feature_remove`, `custom_feature_add`, `custom_feature_edit`, `custom_feature_remove` (the picture has its own
    endpoint, above). It answers
    `{ok, refresh, message, state}` (`message` is a note for a toast, e.g. "Sold for 2 gp 5 sp"); the script redraws from `state`, or - when `refresh` is true because
    something derived changed (`equip`: AC, warnings; the item actions: the lists) - re-fetches the page and swaps
    `#cs-swap`. Requests are sent one at a time, in order. The rules for each live in
    `characters.services.play`.
  Trinkets are not in the wizard yet (see the plan's TODO).
- The Handbook is World's first tab (`/handbook/`, no separate bottom-nav item; its pages belong to World's navigation stack): its contents are one root page (no back button), headed by a **Glossary**
  button that stands out from the section rows (accent-coloured card with an open book marked
  A-Z, `_list_page(glossary_link=...)`/`list.html`) - the glossary reads as the book's first
  chapter, before "Playing the Game". The glossary page itself links back to the contents.
  - `GET /handbook/` (`handbook_overview`) shows the Glossary button, then one toggle heading per
    `rules.HandbookChapter` ("Playing the Game", "Character Origins", "Feats", "Equipment",
    "Spells") over the buttons of its `HandbookSection`s - 22 in all (see
    [Internationalization](#internationalization-i18n) for what is left out). The headings are
    open by default; folding one is remembered for the browser session (`sessionStorage`, in
    `list.html`), so coming back from a section keeps the layout. Each button links to
    `GET /handbook/<id>/` (`handbook_section_detail`), which renders exactly like a
    `Rule`/`Feat`/`Spell` detail page - one open "Description" section, with the section's named
    blocks as toggle headings. A section or block hand-translated for this project shows the
    "Traduzione" badge (Italian only), on the button, the page title and the block heading.
    The tab has a live search box (same `?q=` form as the World lists, drawn under the tab strip -
    `_list_page(searchable=True)`) that searches the **whole handbook** - every section's text,
    not just its name, plus the Glossary's `Rule`s (name and text). While a query is set the search
    box stays put and the chapter toggles below hold only the matching sections (a
    "Glossary" toggle last, for matching rules), each button with up to three snippets (rules: one)
    of where it matched - the enclosing headings as a bold breadcrumb, the match highlighted - and
    "+N more" for the rest. Matching is a case- and **accent-insensitive** substring ("opportunita"
    finds "opportunità", and the highlight keeps the original spelling) of the text *as displayed*
    (tags resolved, metric units on the Italian site) in the active language; names are matched in
    both languages, like the other lists. It is a plain Python scan over the (small) `entries` JSON
    in `apps/frontend/handbook_search.py` (`fold()` is the length-preserving accent stripper), not
    a database query. The other lists' searches are still plain case-insensitive `icontains`.
  - `GET /handbook/rules-glossary/` (`handbook_rules_glossary`, the Glossary) is the `Rule`
    catalog index - its label is just "Glossary", not the source book's "Rules Glossary" section,
    which stays dropped (see [Internationalization](#internationalization-i18n)) - every `Rule`
    linking to `world-rule-detail`. See **Bookmarks**/**Alphabet index** below.
- `GET /world/` (`world`) — five full-height nav buttons, one per browsable `rules` catalog:
  **Backgrounds**, **Classes**, **Species**, **Feats**, **Spells**. (Class Features and
  Subraces were dropped again after being tried - the former duplicated what's already on each
  Class's own detail page, and the 2024 rules have no subraces at all, so `db/species.json` has
  nothing to list there.)
- Each catalog has a **list page** (`list.html`) showing every row of that `rules` model, and a
  **detail page** (`detail.html`) per row, both built generically by `views.py` (`_list_page`/
  `_detail_page` helpers) rather than one bespoke template per model:
  - Detail pages render as a `facts` key-value block (short fields - size, page number, casting
    time, ...) plus a list of `sections` (Lore/Description/Traits/... - longer prose).
  - `Class`/`Species` list rows render as full-width banner buttons using real artwork
    (`static/images/classes/`, `static/images/species/` - one PNG per class, most species) with
    the row's name and `Class.short_description`/`Species.short_description` (a short,
    hand-written blurb - there's no such field in `db/*.json`, so these were authored directly in
    `apps/rules/management/commands/import_rules_data.py` rather than sourced) overlaid on the
    art. Rows without artwork (e.g. Aasimar) fall back to a plain text row like every other list.
  - **Search** (World tabs and the Glossary) is live from the first typed letter: the
    plain GET form is enhanced by a script in `base.html` that re-fetches the page and swaps
    just `#search-results`. `_list_page(searchable=True)` shows the search box without any tab
    strip (`world_tabs=True` shows one above it) - the Handbook contents and the Glossary both use it.
  - **Clear filters**: every search form that has filters (`_search_form.html` - the World lists,
    the sheet's Features/Spellbook lists and its three "add" overlays) ends its filter row with a
    "Clear filters" button. It shows only while a filter is set (CSS `:has()` on the form: a
    non-"All" pill, a ticked box, a picked dropdown), and puts every pill/checkbox/dropdown back to
    "no filter" (`static/js/filter_clear.js`, delegated, so it also works in the fetched overlays)
    while leaving the search text alone. It then fires a `filtersclear` event on the form: the
    World lists re-fetch (`base.html`), the sheet re-filters its rows in the browser
    (`character_sheet.js`).
  - **Alphabet index** (`_list_page(alphabet=True)`, Glossary only): a right-edge A-Z strip -
    press or drag along it and a big letter popup names the letter under the finger, every entry
    not filed under it (`_index_letter()`: first letter, accents stripped) fades out, and the list
    scrolls to the first match. Pure client-side (script in `list.html`, bound on `document` so it
    survives live search swapping the strip).
  - **Bookmarks**: every World element page (Background/Class/Feat/Species/Spell/Rule) has a
    bookmark button in the header, left of the account and language switches, and every list row
    (World tabs, Glossary) has one at its right end (`frontend.Bookmark`, toggled by
    `POST /bookmarks/toggle/`; the scripts post in the background - on a list, then re-fetch and
    swap `#search-results` keeping the scroll position - and a plain form post redirects back).
    Bookmarked rows of the current (searched/filtered) list are moved out of the list into a
    highlighted block at its top (`_list_page(bookmark_kind=...)`), not shown twice. Stored as
    `(user, kind, object_id)` in its own table, **not** a flag on each `rules` model -
    `import_rules_data` wipes every `rules` table, which would have erased the bookmarks. They are
    per account (see **Accounts** below); signed out, the buttons and the bookmarked block simply
    aren't rendered. List/detail responses are `never_cache`d so back-navigation never shows a
    stale bookmark state.
  - **Accounts** (`accounts.py`, `GET/POST /account/`, `POST /account/logout/`): password-less on
    purpose, for now - typing a name signs you in as that `auth.User` (case-insensitive), creating
    it if it's new, so a few friends each get their own bookmarks. It is identity, not
    authentication: anyone can type anyone else's name. Accounts are created with an *unusable*
    password, so real password auth later is just `set_password()` plus a password field on
    `SignInForm` - no schema change - and name-only sign-in is refused for any account that
    already has a usable password (e.g. a `createsuperuser` admin). The header's account button
    (right of the language switch) links to the account page: signed in it is a circle with the
    first letter of the name (accent-coloured); signed out it reads "Login" and is shaped exactly
    like the language button.
  - **Cloudflare Access sign-in** (`cloudflare_access.py`): the app is exposed through a
    Cloudflare tunnel with Access (Google) in front. When `CF_ACCESS_TEAM_DOMAIN` and
    `CF_ACCESS_AUD` are both set, `CloudflareAccessMiddleware` requires the signed
    `Cf-Access-Jwt-Assertion` on every request (403 otherwise; the plain e-mail header is never
    trusted), verifies it (PyJWT: signature against the team's `/cdn-cgi/access/certs`, audience,
    issuer, expiry) and signs the visitor in as the `auth.User` whose `email` matches, creating it on
    the first visit with the *full e-mail as username* (so `anna@elsewhere` can never become the
    `ADMIN_ACCOUNTS` entry `anna`) and an unusable password. Existing accounts are attached to an
    address with `manage.py link_account_email <username> <email>`; do that *before* that person's
    first visit or they get a fresh, empty account. The account page's "Sign out" then points at
    Access's own logout. With either setting empty (local runs, tests) the middleware is off and the
    password-less sign-in above applies.
  - `_list_item.html` gives an item with a `page` (a Handbook chapter section, a Glossary `Rule`)
    a "Page N" detail line under its name - no icon.
  - `apps/frontend/entries_render.py` turns the raw 5etools `entries` JSON blobs (used by
    `Background`/`Species`/`Class`/`Feat`/`Spell`/`Rule`) into safe HTML: nested
    headings/lists/tables/insets/"choose N" groups, and - via `_ReferenceLinker` - turns any
    literal `{@variantrule ...}`, `{@spell ...}`, or `{@feat ...}` tag into a real link to that
    row's own detail page (matched by name against `rules.Rule`/`Spell`/`Feat`).
  - `Species.entries` (traits) and a Class's per-level `Feature` rows get extra treatment
    instead of the generic renderer: `render_trait_cards()` puts each trait in its own visually
    distinct card, and `render_class_features()` does the same per feature while further
    grouping cards into collapsible `<details>` toggles by level (the lowest level starts
    expanded). Only a card's own title is styled as the card heading - a named sub-block nested
    inside a feature's own text (e.g. Wizard's Spellcasting feature has "Cantrips"/"Spellbook"
    sub-sections) falls back to a plainer heading style, so the two are never confused.
  - **Options** (`OptionalFeature`: Eldritch Invocations, Metamagic, Battle Master Maneuvers) are
    part of the World Features list: an **Options** Type pill, an **Option type** pill row and the
    Class dropdown (which also narrows options), each row using its class's icon
    (`features_classes/<class>.jpeg`) and opening `world-option-detail`. The class features that
    just list them ("Eldritch Invocation Options", "Metamagic Options", "Maneuver Options") render
    their `refOptionalfeature` pointers as tappable link rows, and `{@optfeature}` tags link too.
    Those three features are hidden from the Levels/Subclasses tabs and the Features list: the
    class page (Warlock, Sorcerer, Fighter) has an **Options** tab named after them instead, listing
    the options as link rows, and the `{@filter ...optionalfeatures...}` links in "Eldritch
    Invocations"/"Metamagic"/"Combat Superiority" lead to it.
  - There's no standalone browsing list for `rules.Rule` - `world/rules/<slug>/` exists purely
    as the landing page for `{@variantrule ...}` links found in other pages' text, so its back
    button returns to the World hub rather than to any specific list.
- `/manifest.json` and `/serviceworker.js` are served by `django-pwa` (`pwa` in
  `INSTALLED_APPS`, `path("", include("pwa.urls"))` in `config/urls.py`). Config lives in
  `config/settings.py` (`PWA_APP_*` / `PWA_SERVICE_WORKER_PATH`).
- The service worker itself is a real file at `static/js/serviceworker.js` (network-first for
  same-origin requests, falling back to cache only when offline - a stale cached page would
  otherwise silently ignore a language switch).
- PWA icons are placeholder solid-color PNGs at `static/images/icons/` (192/512/180px) - still
  unreplaced, unlike the class/species artwork above.
- See [Running it](#running-it) above for how static files (this artwork included) actually get
  served in each of the two run modes - it differs between the container (WhiteNoise) and host
  dev (`staticfiles_urlpatterns()`).

#### Internationalization (i18n)

The UI needs to support multiple languages with a switcher, so this uses **Django's built-in
`gettext` i18n framework**, not a database table of translated strings. Why:

- It's the Django-native, zero-extra-infrastructure way to translate strings that live in code
  (templates, view text) - `{% translate "..." %}` in templates, `gettext()` in views, compiled
  `.mo` files loaded once at process start (no per-request DB query, no cache invalidation to
  get wrong).
- A DB table is the right call for content editors changing copy *without a deploy* - not the
  case here, this UI text ships with the code same as everything else.
- Standard tooling (`manage.py makemessages`/`compilemessages`) extracts and compiles strings,
  and every translator-facing tool speaks `.po`, so no bespoke admin UI is needed for someone
  to contribute a translation.

**Game content is a different problem, solved differently.** The `rules` tables (spell names,
feat text, handbook prose, ...) are bulk-imported from `db/`, not developer-authored strings, so
`gettext` is the wrong tool for them. They use **django-modeltranslation** instead: each
translated field (`HandbookSection.name`/`.entries` so far - registered in
`apps/rules/translation.py`) gets one extra column per language (`name_en`/`name_it`), and the
plain attribute (`section.name`) returns the active language's value, falling back to English
when that translation is empty (`MODELTRANSLATION_FALLBACK_LANGUAGES`). Services and
templates keep reading `section.name` unchanged, and a half-translated catalog never shows blanks.
No duplicate tables - just columns on the existing ones.

Italian text is *not* edited in the database. It lives in `db/it/*.json` next to the English
source (so it's versioned, diffable, and survives `import_rules_data`'s wipe-and-reload) and is
loaded by `import_rules_data` - or, to update translations alone without wiping anything, by
`manage.py import_translations`. `db/it/handbook.json` is a sparse overlay keyed by section id
that mirrors the English row's tree (same nesting and list positions, block `id`s repeated as an
alignment check, language-neutral keys inherited); `null` or a trailing omission means "no Italian
text for this part". The format is spelled out in `apps/rules/handbook_source.py`, which also does
the merge and raises with the exact path when the file drifts from the English source.
The file also names the chapters (`{"007": {"name": "Come si gioca"}, ...}`, keyed by chapter id) and
flags what was hand-translated: a row lists `"_self": ["name", "entries"]`, a single block inside
`entries` carries `"self_translated": true` (a named block, badged on its heading, or a `table`,
badged on its caption) - the site badges those "Traduzione" (Italian only). The same works in
`db/it/rules.json` and the other catalog files. Where a gap has no heading of its own to carry the
flag (a rule's unnamed intro paragraph and list - `action`, `area-of-effect`, `condition`), the
row lists `"_self": ["entries"]` and its "Description" heading is badged instead.
`{@tag ...}` markup is mirrored from the English text with the *English* lookup key kept and the
Italian wording in the display slot - `{@skill Perception|XPHB|Percezione}`,
`{@area Combattimento|06b|x}` - so the reference linker (which matches English catalog names)
still resolves them.

**The handbook shows the same content in both languages.** It's translated from the Italian SRD
5.2.1 (`IT_SRD_CC_v5.2.1.md`); what it doesn't have - the "Playing the Game" intro, "Rules Glossary", "Player or DM?", the three
worked examples and two small boxes - is listed in `OMITTED_ROW_IDS` / `OMITTED_BLOCK_IDS` in
`handbook_source.py` and dropped from the *English* handbook as well, at import time, rather than
Italian pages showing English text. To bring a part back: translate it in `db/it/handbook.json`,
take its id off the omit list, and re-run `import_translations`. A test guarantees no English text
survives in the Italian handbook. (The model-level English fallback still exists for any future
translated field that's only partly filled in.) `{@dc 10}` renders "DC 10" / "CD 10" via
`gettext`.

The SRD chapters added after "Playing the Game" (Character Origins, Feats, Equipment and Spells
rules text, from `handbook_extended.md`) are Italian-complete: the text comes straight from the
Italian SRD, except **"Character Classes"** (the class-chapter intro - not in the SRD), which was
translated for this project and is flagged `self_translated`. Both texts were PDF extractions with
the same layout defects (page footers cutting sentences, sidebars and the spell "Range" entry
printed in the wrong place, Italian weapon properties alphabetised); they were repaired while
converting, so the two languages line up block for block. Two consequences to know: the Italian
weapon properties/masteries follow the English order (the overlay is positional), and the
"Selling Equipment" sidebar sits at the end of "Coins". The weapon and armor *tables* are not part
of it - they live in the `Equipment` catalog.

**The other catalogs** (`Spell`, `Feat`, `Rule`, `Species`, `Background`, `Class`, `Subclass`,
`Feature`, `Equipment`, ... - all registered in `apps/rules/translation.py`) work the same way but,
unlike the handbook, **nothing is removed for lacking Italian text**: a row or a part with no
translation keeps showing its English, so these pages can be partly Italian. Each has a file
`db/it/<model>.json` (`{row id: {field: overlay}}`, same overlay format), loaded by
`apps/rules/translation_sync.py` (`TRANSLATED_CATALOGS` maps model -> file -> fields) at the end of
`import_rules_data` and by `import_translations`. Search matches either language's name, and
`{@tag}` lookups use each row's English name (`name_en`), so links still resolve when the display
text is Italian.

**Filled from the official source** (`IT_SRD_CC_v5.2.1.md`, extracted with throwaway scripts:
paragraph-by-paragraph alignment of the Italian markdown to the English `entries` tree, tags
mirrored by an English-to-Italian term dictionary, a first pass accepting a row only when the two
structures line up exactly and a second paragraph-level pass filling most of what that rejected):
the 17 SRD feats; the 339 SRD spells; 114 rules; all 12 classes plus their 12 SRD subclasses and
class/subclass features; the 9 SRD species; the 4 SRD backgrounds; and the SRD-sourced equipment
items - collectively, this is the content that isn't in any row's `self_translated_fields` (below).

**Everything else has been hand-translated for this project instead** (there's no official
Italian source for it - PHB-only flavor text, or 2024-refresh content the SRD extract doesn't
cover): every species'/background's/class's narrative lore, the non-SRD
species/backgrounds/subclasses/feats/spells, skills, senses, languages, masteries, abilities,
weapon properties, optional features, and the class/subclass features the SRD pass couldn't
align. Each translated row's overlay entry in `db/it/<model>.json` can carry a sibling `"_self"`
key (not a real field, so `sync_catalog()`'s per-field loop ignores it) listing exactly *which*
of that row's own fields are hand-translated, e.g. `"_self": ["lore"]` on a species whose
`name`/`entries` are official SRD text but whose `lore` isn't - `translation_sync.sync_catalog()`
reads that list into the row's own `self_translated_fields` column (one per translated model,
alongside the existing `srd` flag many of them already had). The frontend shows a small
"Traduzione" badge wherever a hand-translated field is actually displayed - next to the page
title only if `name` itself is hand-translated, next to a "Lore"/"Description"/"At Higher
Levels" section heading only if *that* field is, and on the individual feature/subclass cards
inside a Class page - deliberately field-scoped rather than one flag for the whole row, so a
page that mixes official and hand-translated content (like that species: official name and
traits, hand-translated lore) only marks the part that actually is. `_self_translated()` and
`_badged_heading()` in `views.py`, and `self_translated_badge()` in `entries_render.py`, are the
three pieces that wire this up.

The one exception is a **homebrew** row: a species in `HOMEBREW_SPECIES` (`views.py` - only
`Grung`, Volo's Guide converted by hand; the `species` table doesn't store a source, so it's a
constant rather than a field) shows an outlined "Homebrew" badge (`homebrew_badge()` in
`entries_render.py`, same in both languages) on its title in the list and on its page, and *no*
"Traduzione" badge anywhere - its text is unofficial by definition, so flagging the translation
as well would add nothing.

The two gaps this still leaves **on purpose**: `Equipment.entries` (never rendered by any page
today - only `Equipment.name` shows up, via `{@item}` tags and equipment lists, so translating a
body of text nothing displays would be pure invisible busywork), and the `Feature` rows FK'd to a
`Species`/`Feat` (these duplicate text already translated on the parent's own `entries` field -
see `Feature`'s docstring - and, unlike a `Class`'s per-level features, are never the thing an
actual page renders either, so translating them a second time would duplicate work for no visible
gain).

**Measurements are metric on the Italian site**, via `apps/frontend/units.py` - conversion
factors (1 ft. = 0.3 m, 1 mile = 1.5 km, 1 lb. = 0.5 kg) taken from the SRD's own conversions
(confirmed against the translated handbook's Travel Pace table and the equipment weights) rather
than the real-world values, since that's what the Italian book actually prints. It converts, only
while Italian is active: a class table's `bonusSpeed` cells (e.g. a Monk's Unarmored Movement),
a Species' Speed/Darkvision facts, and a Spell's Range fact and filter option labels. For English
text that still shows on an Italian page because that field isn't translated yet,
`metricize_text()` (called from `entries_render._render_text()`) converts any imperial number it
finds in the fallback prose itself ("30 feet" -> "9 meters") - the number goes metric even where
the sentence around it is still English, rather than mixing in an Italian unit word that would
read worse in an English sentence. Class table column headers sourced straight from
`ClassLevel.columns` (e.g. "Rages", "Unarmored Movement") are plain `gettext()` calls in
`world_class_detail()`, translated via the same `django.po` file as any other UI string - unlike
the paragraph-level game content, these are effectively a small fixed vocabulary, one column
header per class.

**The About-tab facts are translated too** - `Ability` and `Skill` now have full `db/it/*.json`
data (all 6 abilities, all 18 skills, straight from the handbook's own tables), so `Class`'s
`primary_ability_display`/`saving_throws_display` (`Ability.name` via FK) and a Background's
Skills fact (`Skill.name` via M2M) read Italian automatically - no view code needed, since those
are ordinary translated-model fields. The `and`/`or` joining multiple primary abilities is the
one piece of that display string that isn't a model field (`Class.primary_ability_conjunction`
stores the bare source word) - translated with plain `gettext()` inside the model property
itself, not `apps.frontend.units`, since `rules` must not depend on `frontend` (see
"Architecture" above). Everything else on those facts is a raw *code*, not a name a catalog model
already carries: a Species' size letter and creature-type word, and an armor/weapon proficiency
category or tool-choice placeholder
(`Class.armor_proficiencies`/`weapon_proficiencies`/`tool_proficiencies`, `Background.tools` -
see those models' docstrings for the shape). These go through dedicated `(english, italian)`
dicts in `views.py` (`_SIZE_LABELS`, `_CREATURE_TYPE_LABELS`, `_ARMOR_CATEGORY_LABELS`,
`_WEAPON_CATEGORY_LABELS`, `_TOOL_CHOICE_LABELS`) rather than `gettext()` - confirmed collision
risk for some of these words (e.g. the existing generic "All" filter pill is already "Tutti", but
a weapon category's "All" needs the grammatically different "Tutte"), so a shared flat `.po`
catalog isn't safe for this particular vocabulary. A *named* tool proficiency (e.g. "thieves'
tools") is the source's own lowercase `Equipment` name, so it's resolved through that row's own
translation instead of a separate mapping.

**A Spell's own facts needed the same treatment.** `school`, `casting_time` and `classes` are
raw structured data (see `Spell`'s docstring), not `entries` prose, so the translation pipeline
never touches them - they were showing English on the Italian site even once everything else on
the page was translated. Fixed the same way as the codes above: `_SCHOOL_LABELS` (all 8 schools -
note the classic Italian D&D swap, English "Conjuration"/"Evocation" are Italian "Evocazione"/
"Invocazione", the other way around from what the cognates suggest, confirmed against this
project's own already-translated Evoker subclass, "Invocatore", and its Evocation-school
features) and `_CASTING_TIME_UNIT_LABELS` are `(english, italian)` dicts like the others;
`_CASTING_TIME_CONDITIONS` (a Reaction spell's free-text trigger, e.g. "which you take when you
are hit by an attack roll...") is instead a plain `{english: italian}` lookup by exact sentence,
since there are only ever a handful of distinct ones across the whole catalog and it's prose, not
a code; `_classes_by_name()` resolves each `classes` entry through the matching `Class.name`
(already translated), the same shape as `_proficiency_label()`'s `Equipment` lookup above -
`_format_spell_classes()` uses it to render each class as a link to its own detail page, and the
World > Spells class filter's `_class_name()` uses it for a plain label. Every `classes` entry
matches a real `Class` row now - the one name that didn't, `"Artificer"` (not one of this
project's `Class` rows - see `Spell`'s docstring), is dropped entirely at import time instead of
kept as an unlinked fallback, at the project owner's request. Fixing `_format_casting_time()` also
surfaced
a pre-existing bug in *both* languages: a condition's `{@variantrule ...}` markup was being shown
as a literal, un-rendered tag rather than resolved to a link, since a fact's value only ever went
through a plain `{{ value }}` (auto-escaping, no tag handling) - now routed through the new
`entries_render.render_text()`, the same tag resolution `entries` prose gets but without its
`<p>` wrapper, since this is one short phrase inside a larger sentence, not a block of its own.
The World > Spells filter row and each spell's list-page subtitle went through the same fix for
`school`/`classes`/`casting_time` labels.

**A Feat's `category`** (e.g. "Fighting Style", "Origin") is the same kind of raw, non-`entries`
code, decoded from a short source letter at import time (see `Feat`'s docstring) - translated via
`_FEAT_CATEGORY_LABELS`/`_format_feat_category()`, the same `(english, italian)`-dict pattern,
on the feat detail page's own Category fact, the Feats list's per-row subtitle, and the category
filter's pill labels. A "Fighting Style (P)"/"(R)" sub-variant keeps its parenthetical suffix
untouched (a class-group marker, not English prose) and only translates the base word.

**Every World list page marks a hand-translated title too**, not just its detail page: each
`items` entry's `"name"` is built with the same `_badged_heading()`/`_self_translated()` pair the
detail pages use (`obj.name` checked against `self_translated_fields`), so e.g. Artisan (a
hand-translated background) shows the badge in the Backgrounds list exactly as it does on its own
page, and an officially-translated row like Alert shows none. This covers every catalog's list
(Backgrounds, Classes, Feats, Species, Spells) and their in-list search sub-results (Subclasses/
Features found from the Classes search box, Traits from the Species one).

**`Background` gained a `short_description`** (a one-line World-menu blurb), matching
`Class.short_description`/`Species.short_description` - it had no such field before, so its list
page was the only one of the three missing a subtitle. Same shape as those two: hand-written
English in `BACKGROUND_SHORT_DESCRIPTIONS` (`import_rules_data.py`, no source for it in `db/`
either) with a hand-translated Italian counterpart in `db/it/backgrounds.json`.

**How it's wired**: `LANGUAGES = [("en", ...), ("it", ...)]` + `LocaleMiddleware` (in
`config/settings.py`) + `path("i18n/", include("django.conf.urls.i18n"))` (in `config/urls.py`)
gives a `POST /i18n/setlang/` endpoint for free - that's the "change language with a button"
mechanism, and it's what `base.html`'s language switcher form posts to. It sets a cookie
(session too, if one exists) so the choice persists across requests without a URL prefix
(`/en/...`, `/it/...`) - simpler than `i18n_patterns` for a cookie/button-driven switch, though
that's the option to reach for later if language ever needs to be shareable via URL.

Translations live in `locale/it/LC_MESSAGES/django.po` (English is the source language - the
`msgid`s themselves, no `.po` needed for it). One gotcha already hit and fixed: the switcher
shows "English"/"Italiano" as hardcoded literals in `base.html`, not via Django's
`get_available_languages` tag - that tag returns each language's name translated into the
*current* language (so it'd render "Italian" while browsing in English), not each language's
own autonym, which is the correct convention for a language switcher.

#### Interactions (activity tracking)

`frontend.Interaction` has one row per page opened (`kind="view"`) and per change posted
(`kind="action"`), written by `InteractionMiddleware` for every request that is not a static file,
the manifest/service worker or a portrait: who (`user`/`username`, or a short `session` hash when
signed out), where (`route` = the URL name, `path`, `object_id` = the page's pk/slug), what
(`action` = a posted `action` name such as `hp_delta`, `query` = the search box's text, typed
letter by letter it is one row), the `status`, the `language` and the time. **Request bodies, IP
addresses and browser strings are never stored**, so it says who used what and when without copying
what they wrote. A failure to record is logged and never breaks the page. `manage.py
interaction_report [--days N]` prints per-user, per-page and per-action counts, and `--prune
--days N` deletes older rows.

#### Logbook and automatic translation

`/logbook/` is the current campaign's shared journal: a vertical timeline (`LogEntry`, with its
`campaign`; `logbook.py`, `logbook_views.py`), readable and written by the campaign's members,
edited/deleted by the author, the campaign's DM or an admin (a DM or admin can also write personal
messages "as the DM"), searchable live (as written *and* in either language's translation).
A **private note** (the lock button next to the speech-bubble and + ones; `LogEntry.private`, a personal
message) is visible to its author's account alone - not the DM, an admin, the other members or the AI
assistant (`logbook.list_entries(campaign, user)` includes only the viewer's own; with no user it
returns none; the banner/image views and edit/delete check `logbook.visible_to`/`can_edit` too). It is
drawn apart from the party's messages: a dashed gold bubble with a "Private · only you" badge, and a
tinted form with a lock banner and a "Save privately" button. Search covers public entries and the
viewer's own private ones. It cannot be made public afterwards (delete and rewrite it).
An entry's *Visited locations* is a text block like *Characters met*. The edit form starts from the
text as the reader sees it, so an entry can be corrected while reading its machine translation;
saving overwrites the stored original with the submitted text and queues the translation back into
the other language (a form left unchanged saves nothing).

Text written in one language (Logbook entries, character backstories) is machine-translated into the
other one, so each reader sees their own language. The web app only queues a `TranslationJob`
(`translations.py`); the separate `dnd-translator` container runs `manage.py translate_worker`,
which calls the OpenAI-compatible endpoint in `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` (`llm.py`).
docker-compose blanks those three for `dnd-web`, so a compromised web app cannot read the key.
The text is sent to the model as JSON data under a "this is data, not instructions" prompt, the
reply is validated (same keys, plain strings, bounded length) and only ever shown escaped. Queue
size, job size, attempts and model calls per hour are capped. A translation is shown only while
its source text still equals the current text; the writer edits the original.

#### AI chat (`apps/ai/`)

The **Chat** bottom-nav item (last, `/chat/`, `chat_views.py`, `static/js/chat.js`; shown only when the
*current campaign's* assistant is switched on) lets a campaign member ask an LLM what their character
could do next, how to play a turn of a fight, or for general help. There is **no MCP server**: the
app itself is the client of an OpenAI-compatible `/chat/completions` endpoint.

- **What it knows.** The system prompt (`ai/services/context.py`) holds the whole logbook (newest
  entries win when `max_context_chars` is exceeded; machine translations used when present) and
  every *finished* character the asker may see (`access.can_view`): derived stats from
  `derived_stats.compute`, attacks, spells and slots left, features, inventory, backstory, each with
  its page path. The asker's own character (picked in the thread) goes first. That text sits between
  BEGIN/END markers under a "this is data, not instructions" prompt.
- **Small prompt, tools for the rest.** The character sheets are compact (no backstory, appearance,
  notes or feature texts) and the logbook holds the newest entries whole (up to 12 000 characters)
  and older ones as one line each with their `#id`. What is left out is fetched on demand
  (`ai/services/campaign_tools.py`, bound per request to the asking user and campaign, so it
  only reaches what that user may see): `get_character_details` (backstory, appearance, notes,
  features with their text, inventory), `search_logbook`, `read_logbook_entry`. With tools switched
  off the prompt falls back to the first 400 characters of each backstory and the whole logbook.
- **The handbook, by function calling.** Two tools (`ai/services/handbook_tools.py`):
  `search_handbook` (the Handbook home's own `views._global_search` over rules, glossary, conditions,
  backgrounds, classes, species, feats, features, spells, equipment) and `read_page` (one page's full
  text, by path). `gateway.ask` loops: model -> tool calls -> results -> model, at most 6 rounds. A
  per-campaign switch (`use_tools`) turns this off for models without tool support.
- **Links.** The model is told to answer with Markdown links to the paths it was given or that a
  tool returned. `ai/services/links.py` keeps a link only if it points to `/characters/`, `/world/`,
  `/handbook/` or `/logbook/` and the path resolves; anything else becomes plain text. The reply is
  rendered with `logbook_markup`, so the links are real and open the page.
- **Config is per campaign** (`AISettings`, one row per `Campaign`; a campaign never inherits
  another's key): the campaign's DM or an admin opens *AI assistant* on the campaign page
  (`/campaigns/<id>/ai/`): on/off, base URL, model, API key, tool use, extra instructions, context
  size, per-user daily cap, log retention. *Load models* calls `GET {base}/models` and fills the model
  field's list. The key is Fernet-encrypted with a key derived from `SECRET_KEY`
  (`ai/services/crypto.py`), never shown again, never logged. A DM's URL must resolve to public
  addresses only (`urlcheck.py`, so the server can't be aimed at its own network) and changing it
  requires typing the key again; an admin may use any address (e.g. a local Ollama). Unlike the
  translator's `LLM_*`, the **web container holds these keys** and needs outbound access.
- **Every ask is recorded** in `AIRequestLog` (`ai/services/gateway.py` is the only caller of the
  model): the exact messages sent - context and tool calls included - the reply, token counts, latency;
  on failure `error_detail` holds the HTTP status, the provider's response body or the traceback
  (the key scrubbed), and the same goes to the Python log. Failures while building the context are
  logged too. Pages (`/campaigns/<id>/ai/requests/`, `.../usage/`): the request list (filter by user /
  status, full request and response on each), and usage (totals, per user, per day).
  `manage.py prune_ai_logs` deletes rows past each campaign's retention.
- **Limits** (`ai/services/chat.py`): 2000 characters per question, 6 questions a minute, the
  campaign's daily cap per user, the last 20 messages of the thread sent back. Threads
  (`ChatThread`, `ChatMessage`) are per user and campaign; *New chat* starts another.
- Questions and campaign text go to whatever provider the DM configured; the settings page says so.
- **Streaming.** `POST /chat/send/` answers with server-sent events (`chat_views.py`, read by
  `static/js/chat.js` through `fetch` + `ReadableStream`): `step_start`/`step_end` when the assistant
  searches or reads the handbook (a quiet rail of steps above the answer: shimmering while it works,
  a check and clickable chips for the pages found afterwards, kept with the message in
  `ChatMessage.activity` and shown again when the chat is reopened), `text` (the answer so far,
  already rendered and link-checked by the server, at most every 60 ms), `done` and `error`.
  The provider is read with `llm.chat_stream` (a reader thread that also sends a ping every 10 s of
  silence). The view returns an *async* generator that steps the sync one in the request's own
  thread - a plain sync generator would be collected whole before ASGI sent a byte. Leaving the page
  mid-answer logs an "interrupted" error and stores nothing. The test connection is not streamed.
- **Provider quirks.** A streamed tool call keeps every field the client doesn't know and sends it
  back with the tool result (`llm._merge_call`): Gemini's OpenAI-compatible API puts a
  `thought_signature` in `extra_content` and answers HTTP 400 if it is missing.
- **Versions.** A chat is a tree (`ChatMessage.parent`; `ChatThread.head` = last message of the
  version shown). *Edit* or *Ask again* on a question adds a sibling with its own answer and
  follow-ups; a `‹ 2 / 3 ›` switcher on the question flips between versions
  (`chat.switch_version` shows the newest chain below the chosen one). A new question continues the
  version being shown; the model is sent only the turns that lead to it.
- **Closing the page mid-answer** keeps what had been written (`ChatMessage.partial`, shown as
  "The answer was cut short"), next to the "interrupted" row in the request log.
- **Past chats.** `/chat/history/` lists the user's chats in the campaign (first question, date,
  messages, character), `/chat/t/<id>/` reopens one and continues it, a chat can be deleted; *New*
  reuses a still-empty chat instead of piling up empty ones. Chats are private to their user.
- Copy / Edit / Ask again sit in a footer *inside* each bubble (Copy copies the bubble's text). Logs and the AI pages name people by
  their first name (`accounts.display_name`), not the e-mail used as username.
- `POST /chat/send/` is a same-origin action endpoint like `character_act`, not a public API.

##### Streaming behind Cloudflare

The response carries `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`,
`Content-Encoding: identity` (so `GZipMiddleware` and Cloudflare leave it alone) and
`X-Accel-Buffering: no`, and the first bytes are sent at once; Cloudflare then passes the stream
through (Tunnel and proxied DNS alike). If the answer still only appears all at once:
1. Cloudflare dashboard -> *Rules -> Configuration/Compression Rules* (or *Speed -> Optimization*):
   make sure nothing compresses or rewrites `/chat/send/` (Rocket Loader, Auto Minify and
   "Brotli" must not apply to it); add a rule that disables them for URI path `/chat/send/`.
2. A *Cache Rule* "Bypass cache" for `/chat/send/` (the `no-cache` header is normally enough).
3. Free/Pro plans close a connection after 100 s with no byte (error 524); the 10 s ping keeps it
   open, but a Cloudflare *Worker* or *Page Rule* in front must not buffer either.
4. Behind a Tunnel nothing extra is needed; behind another reverse proxy (nginx, Traefik) turn
   buffering off for that path (`proxy_buffering off;`, or keep the `X-Accel-Buffering: no`
   header) and give it a read timeout above the longest answer.
5. Cloudflare Access only has to let the signed-in session cookie through, as for every page.

## Not in scope (per the architecture doc)

No `users` app, no real auth of its own (identity comes from Cloudflare Access, or the password-less accounts in `frontend` for local runs), no combat system. Campaign membership is the only authorization there is.

## Other files in this repo

`db/*.json` (plus their `*_schema.json` siblings) is the XPHB content dump the `rules` models
above are sourced from — see [Model status](#model-status). `db/spell_classes.json` holds the
`Spell.classes`/`subclasses` lists, which the current dump dropped; see
[docs/data_migration_2025.md](docs/data_migration_2025.md). `IT_SRD_CC_v5.2.1.md` is the Italian SRD
the Italian translations were taken from.

### Versatile weapons

`Equipment.versatile_damage_dice` (the dataset's `dmg2`) is the two-handed damage of a Versatile weapon
(longsword 1d8 / 1d10, not a left/right hand difference). It shows next to the damage everywhere, and
`derived_stats` attacks carry `damage_two_handed` and `two_hands_free` (no shield worn and no other weapon
wielded - the SRD needs both hands for it); the inventory row of a wielded one says which die applies.
Dueling's +2 stays on the one-handed damage only.

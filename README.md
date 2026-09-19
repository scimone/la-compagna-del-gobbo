# la-compagna-del-gobbo

A D&D 5.5e (2024 rules) backend for player logic: characters, character creation/leveling, and the
static rules catalog they're built from.

See [architecture.md](architecture.md) for the full design rationale. This README documents what
exists today and what each placeholder is reserved for.

## Tech stack

- **Django** — models and persistence
- **PostgreSQL** — the database (via `docker-compose.yml`)
- **Django Ninja** — the HTTP API (OpenAPI schema at `/api/docs`)
- **django-pwa** — PWA manifest/service-worker plumbing for the frontend shell
- **WhiteNoise** — serves collected static files (PWA icons, menu artwork, `serviceworker.js`)
  directly from the ASGI app when running in the `dnd-web` container - there's no separate web
  server sharing a volume, and uvicorn doesn't serve static files on its own the way
  `manage.py runserver` does
- **uvicorn** — ASGI server
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
alongside `dnd-db` (Postgres 16, `postgres_data/` bind-mounted for persistence). `dnd-web` waits
for `dnd-db` to report healthy (`pg_isready`) before starting, and its startup command runs
`manage.py migrate --noinput` automatically before uvicorn. `import_rules_data` does **not**
run automatically (see the warning below) - do it once, manually:

```bash
docker compose exec dnd-web uv run manage.py import_rules_data
```

For this mode, `.env`'s `POSTGRES_HOST`/`POSTGRES_PORT` should point at the `dnd-db` service on
the compose network (`dnd-db` / `5432`, per `.env.dist`) - or at an external Postgres instance
reachable from the container, if you'd rather not use the bundled `dnd-db` at all (in which case
that service just goes unused; nothing requires the app to talk to it). App: `http://localhost:3000/`
— API docs: `http://localhost:3000/api/docs`.

**Redeploying** after a code change: `bash update-app.sh` — pulls `git`, rebuilds the image, and
restarts only `dnd-web` (`dnd-db` and its data are left running untouched).

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
- **API: one folder per tag group, one file per endpoint.** Each app's `api/` package has a
  subfolder per Ninja tag (e.g. `api/characters/`, `api/inventory/`). Each subfolder has a
  `__init__.py` that creates the shared `router = Router(tags=[...])` and imports every sibling
  endpoint module so its `@router.<method>(...)` decorator registers on import. Each endpoint file
  contains exactly one route function.
- **No business logic in routers.** Endpoint functions call into `services/` (`rules` and
  `characters` are implemented this way; `builder` isn't yet — see its section below).
- **`rules` is read-only from the API's point of view.** It's populated via
  `manage.py import_rules_data` (see [apps/rules/management/](apps/rules/management/)), not
  through write endpoints.

## App boundaries

Three Django apps form the actual game-logic layering (there's a fourth, `frontend`, covered in
its own section below — it's the web UI shell, not part of this layering):

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
previous format is preserved at `db_old/` — one field, `Spell.classes`/`subclasses`, is still
deliberately sourced from there, see below). The table below describes the *current* `db/`
format; the "Known data-import issues" section further down is historical - it documents bugs
found while building the import against the *old* `db_old/` format and is left as-is for that
reason, not updated for the new one. See
[docs/data_migration_2025.md](docs/data_migration_2025.md) for the 2025 migration's own write-up
(the new format's shape, the field-by-field mapping decisions, and the three data-loss tradeoffs
resolved with the project owner: `Spell.classes`/`subclasses` merged from `db_old/`, lore fields
(now populated - see below) initially left empty pending a fluff-data drop, `HandbookSection`
kept on `db/handbook.json` copied verbatim from `db_old/`).

| Model | Status | Source | Notes |
|---|---|---|---|
| `Rule` | Defined | `db/rules.json` (`variantrule`) | 114 rows |
| `Skill` | Defined | `db/skills.json` | `ability` is a FK to `Ability`, keyed by the source's own 3-letter short code (`str`/`dex`/.../`cha`) — see `docs/data_migration_2025.md` §3.1 |
| `Ability` | Defined | `db/abilities.json` | 6 rows (Strength, Dexterity, Constitution, Intelligence, Wisdom, Charisma) - a first-party source now (was scraped from `db_old/handbook.json`'s "Ability Descriptions" table). `id` is the source's own short code (`str`, `dex`, ...), not a slugified name - every other domain references abilities by this same code. Referenced by `Skill.ability`, `Class.primary_abilities`/`saving_throw_abilities`/`spellcasting_ability`, `Spell.saving_throw_abilities` |
| `Sense` | Defined | `db/senses.json` | |
| `Mastery` | Defined | `db/masteries.json` | |
| `EquipmentType` | Defined | `db/equipment-base.json` (`itemType`) | 23 rows. New - the old format had no such catalog, only a free-text `Equipment.category` string. `Equipment.type` FKs here now |
| `EquipmentGroup` | Defined | `db/equipment.json` (`itemGroup`) | 6 rows. New - a named category of interchangeable items (e.g. "Arcane Focus"); `focus_classes` M2Ms to `Class` |
| `EquipmentProperty` | Defined | `db/equipment-base.json` (`itemProperty`) | 9 rows. No top-level `name` in the source (display name lives at `entries[0].name`) - `id` is `slugify(abbreviation)` |
| `Equipment` | Defined | `db/equipment-base.json` (`baseitem`, 94 rows) + `db/equipment.json` (`item`, 123 rows) | 217 rows total - an exact split of the old single flat catalog, not new content. `type`/`properties`/`masteries`/`group` are real FKs/M2Ms now (were a free-text `category` plus JSON ref lists); `pack_contents` is a new self-M2M (`EquipmentPackContent`) for pack contents (e.g. Burglar's Pack -> Backpack, Candles, ...) |
| `EquipmentPackContent` | Defined | `db/equipment.json` (`item.packContents`) | 65 rows. New - resolves a pack's contents to real `Equipment` FKs with a quantity, where the old format left this as unparsed prose |
| `Species` | Defined | `db/species.json` (`race`) | 11 rows - 10 XPHB plus `Grung` (source VGM), which is absent from the new source drop as shipped (not filtered by this project) and was added back by hand afterward, at the project owner's request, converting `db_old/species.json`'s row into the new format - see `SPECIES_SHORT_DESCRIPTIONS` in `import_rules_data.py`. `fly_speed`/`swim_speed`/`climb_speed` were dropped (no source left for them, and verified zero real data loss - every surviving species already had all three at 0, including the hand-added `Grung`); `speed` is now a plain int. `darkvision` is new |
| `Background` | Defined | `db/backgrounds.json` | `skills` is a real M2M to `Skill` now (was a comma string); `feat` is a real FK to `Feat` now (was a bare name string); `ability_scores`/`tools` keep the source's own structured choice/grant JSON rather than a free-text summary |
| `BackgroundStartingEquipmentOption` | Defined | `db/backgrounds.json` (`startingEquipment`) | 108 rows. New - a background's "choose A or B" starting gear, resolved to real `Equipment` FKs (or a gold value) where the old format left this as unparsed prose. Two picks (e.g. Acolyte's "Holy Symbol") name an `EquipmentGroup` instead of one concrete item - a `group` FK covers those; displayed on the background/class detail page as a "Starting Equipment" section |
| `Feat` | Defined | `db/feats.json` | `prerequisite` is a structured JSON list now (ability/level/feature/proficiency requirements), not one free-text string |
| `Class` | Defined | `db/classes.json` (`class`) | Core metadata; per-level progression is `ClassLevel`. `armor_proficiencies`/`weapon_proficiencies`/`tool_proficiencies` are the source's own structured JSON now (were comma-separated text); the old free-text `proficiencies` summary field and skill-choice regex are gone (see `ChoiceDefinition`). `spellcasting_ability`/`caster_progression` are new. `primary_ability_conjunction` ("or" vs "and") is now derived structurally from the source's own shape instead of a string-pattern parse — see `docs/data_migration_2025.md` §3.6 |
| `ClassLevel` | Defined | `db/classes.json` (`class.classTableGroups`/spell progressions) | `spell_slots`/`cantrips_known`/`spells_known_or_prepared` are dedicated fields now (the source gives these as structured per-level progressions); `columns` keeps whatever's left (e.g. Barbarian's Rages/Rage Damage, Warlock's pact-magic Slot Level) |
| `ClassStartingEquipmentOption` | Defined | `db/classes.json` (`class.startingEquipment.defaultData`) | 93 rows. New - same shape as `BackgroundStartingEquipmentOption`, for a class's own starting-gear choice |
| `Subclass` | Defined | `db/classes.json` (`subclass`, 48 rows) | Already pre-filtered to XPHB in the source (no more `if source != "XPHB"` filtering needed). `additional_spells` (bonus spells) is new. `description` is still the granting level's flavor text, but the new source already keeps it as its own addressable record pointing at its sibling features via `refSubclassFeature` markers rather than bundling them inline - see [Known data-import issues](#known-data-import-issues) Issue 1 and `docs/data_migration_2025.md` §3.6 for how this changed |
| `SubclassLevel` | Defined | `db/classes.json` (`subclassFeature`) | A pure level marker - no `features` field of its own; its features are the `Feature` rows FK'd back to it |
| `Spell` | Defined | `db/spells.json` | `casting_time`/`range`/`duration`/`components` are structured `JSONField`s now (the source gives nested objects, not display strings). `saving_throw_abilities` is new (a M2M - up to 3 spells name more than one ability, verified against all 391). `classes`/`subclasses` are a deliberate exception: the new source dropped this data with no replacement anywhere, so these two fields are still populated from `db_old/spells.json` by exact name match — see `docs/data_migration_2025.md` §2/§3.4 |
| `Language` | Defined | `db/languages.json` | |
| `OptionalFeature` | Defined | `db/optionalfeatures.json` | `prerequisite` is structured JSON now, same treatment as `Feat.prerequisite`. `consumes_resource_name` is new (names the resource a pick spends, e.g. "Superiority Die" - relevant to the "Open design question" below) |
| `Proficiency` | Defined | `db/classes.json`, `db/backgrounds.json` | 47 rows - `Background.skills` moved off this model entirely (a real M2M now, see `Background`). `choice_data` is new: the two previously-excluded tool-proficiency choices (Bard's/Monk's) are now included, since the source gives them as real JSON instead of unparseable "Choose N ..." prose |
| `Feature` | Defined | `db/classes.json`, `db/species.json`, `db/feats.json` | 704 rows (283 class, 261 subclass, 38 species, 122 feat). Class/subclass feature resolution now walks `refClassFeature`/`refSubclassFeature` pointers recursively (a class/subclass's own feature-list field doesn't always enumerate every feature - some are only reachable via a pointer inside a sibling feature's `entries`, e.g. Cleric's Divine Order choice or a subclass's granting-level wrapper) rather than reading one flat list - see `docs/data_migration_2025.md` §3.6. `consumes_resource_name` is new, same as `OptionalFeature`'s |
| `Effect` | Partly defined | derived from `Feature.entries` | 2094 rows (independently cross-checked against the pre-migration verified-correct count) |
| `ChoiceDefinition` | Partly defined | `db/species.json`, `db/backgrounds.json`, `db/classes.json`, `db/feats.json` | 85 rows (up from 27) - the source's own `{"choose": {"from": [...], "count"|"amount"|"weighted": ...}}` idiom replaced the old regex-over-free-text approach and extends to far more of the data (species racial choices, feat ability/skill/save choices, not just the two cases the old format could reliably pattern-match) |
| `HandbookSection` | Defined | `db/handbook.json` (`data`) | 12 rows (15 in the source; "Playing the Game" root, "Rules Glossary" and "Player or DM?" are left out - see the i18n section): the new `db/` drop ships no replacement for this file at all, so it's copied verbatim from `db_old/handbook.json` rather than re-sourced - a deliberate exception, same as `Spell.classes`/`subclasses`. Otherwise unchanged: the source has exactly one chapter, so rather than model chapters as their own grouping, its root block and each of its direct named children ("Rules Glossary", "Player or DM?", "Dice", ...) are flattened into one row each - see the model docstring. `entries` holds each one's own content (arbitrarily nested headings/lists/tables/insets), rendered the same way as every other `entries`-shaped field. **First translated model** - `name`/`entries` also have `_en`/`_it` columns, the Italian side loaded from `db/it/handbook.json` (see [Internationalization](#internationalization-i18n)). Surfaced two edge cases in `entries_render.py` itself - see [Known data-import issues](#known-data-import-issues), Issue 3 |

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
name (correct for its own `/api/rules/features` listing), that query is given an explicit
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

#### The general lesson, for next time

A model being "Defined" (mapped field-for-field) doesn't mean the source's own grouping is
semantically correct, or that nothing downstream of it is redundant:

- **Wrong grouping** (Issue 1): 5etools' JSON is authored for its own renderer, not for this
  schema, and a block that looks like "one feature with sub-details" can actually be "several
  features that got flavor text stapled to the first one." This tends to surface as something
  structurally *off* on a rendered page (not "missing data" but "correct data, wrong shape").
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
| `Proficiency` | A proficiency category (weapon/armor/tool/skill) granted by a `Class` or `Background` |
| `Language` | A language (e.g. Common, Elvish) |
| `Spell` | A spell definition |
| `OptionalFeature` | An optional class feature a player can pick (Eldritch Invocation, Maneuver, Metamagic) |
| `HandbookSection` | A named topic of the player's handbook (rules text, not catalog data) |

**API** (`apps/rules/api/rules/`, tag `Rules`, mounted at `/api/rules`) — one file per endpoint,
implemented (real queries via `services/`, `ModelSchema` responses in `apps/rules/schemas.py`):

`GET /classes`, `GET /classes/{id}`, `GET /classes/{id}/levels`, `GET /classes/{id}/subclasses`,
`GET /classes/{id}/choices`, `GET /subclasses`, `GET /subclasses/{id}`,
`GET /subclasses/{id}/levels`, `GET /species`, `GET /species/{id}`, `GET /backgrounds`,
`GET /backgrounds/{id}`, `GET /backgrounds/{id}/choices`, `GET /feats`, `GET /feats/{id}`,
`GET /features`, `GET /features/{id}`, `GET /features/{id}/effects`, `GET /equipment`
(`?category=`), `GET /equipment/{id}`, `GET /equipment-properties`, `GET /masteries`,
`GET /skills`, `GET /senses`, `GET /languages`, `GET /proficiencies`, `GET /spells`
(`?class=`, `?level=`), `GET /spells/{id}`, `GET /rules`, `GET /rules/{key}`,
`GET /optional-features`, `GET /optional-features/{id}`

`Effect` and `ChoiceDefinition` are deliberately nested under their parent (`/features/{id}/
effects`, `/classes/{id}/choices`, `/backgrounds/{id}/choices`) rather than given flat top-level
endpoints — see the [Model status](#model-status) table for why they're only useful in that
context. There's no standalone `/tools` endpoint either (see the removed-models note above); a
`?category=tool` filter on `/equipment` covers it.

**Services** (`apps/rules/services/`, one file per resource domain): `class_.py`, `subclass.py`,
`species.py`, `background.py`, `feat.py`, `feature.py`, `equipment.py`, `skill.py`, `sense.py`,
`language.py`, `optional_feature.py`, `proficiency.py`, `spell.py`, `rule.py` — plain functions
returning querysets/instances, no HTTP concerns. Path-validity checks (e.g. `list_class_levels`
404ing if the class doesn't exist) live here, not in the endpoint files.

### `apps/characters/` — persisted character state

The actual player characters. No auth, no ownership — any character can be read/managed by
anyone, matching the "no users app" decision in the architecture doc.

**Models** (`apps/characters/models/`, one file per model) now have real fields — there's no
external data source to import here (this is app-generated state, not static content), so
"defined" instead means: real fields, real FKs into `rules`, verified by actually building one
complete level-5 multiclass-ready character through every model and reverse relation at once (a
Human Fighter/Battle Master, exercising every FK — species, background, class, subclass, a
feature, a feat, an optional feature, a language, skill + armor proficiencies, a sense, an
inventory item, currency, a resource — with no constraint violations).

| Model | Represents |
|---|---|
| `Character` | A player character. Ability scores are plain fields (current totals), not a separate one-row-per-ability table — see `CharacterAbilityScoreIncrease` below for why. AC/HP-max-aside/initiative/passive Perception etc. are deliberately *not* fields: they're derived from everything else and belong in `builder.services.derived_stats`, not persisted (a stored value can silently go stale when a feature/item changes; a computed one can't) |
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
| `CharacterCurrency` | The coin purse — a true 1:1 with `Character` (`character` is both the FK and the primary key) |
| `CharacterSpell` | A spell a `Character` knows/has access to, with `prepared`/`always_prepared` flags |
| `CharacterResource` | A limited-use resource (Rage, Sorcery Points, Superiority Dice, ...) with `max_uses`/`current_uses`/`reset_on` |

**API** (`apps/characters/api/`, mounted at `/api/characters`), split into four tag folders,
one file per endpoint:

- `api/characters/` (tag `Characters`): `GET /`, `POST /`, `GET /{id}`, `PATCH /{id}`,
  `DELETE /{id}`, `GET /{id}/sheet` (see below for what `sheet` does and doesn't include).
- `api/inventory/` (tag `Character Inventory`): `GET /{id}/inventory`, `POST /{id}/inventory`,
  `PATCH /{id}/inventory/{item_id}`, `DELETE /{id}/inventory/{item_id}`,
  `POST /{id}/inventory/{item_id}/equip`, `POST /{id}/inventory/{item_id}/unequip`,
  `GET /{id}/currency`, `PATCH /{id}/currency`.
- `api/spells/` (tag `Character Spells`): `GET /{id}/spells`, `POST /{id}/spells`,
  `DELETE /{id}/spells/{spell_id}`, `POST /{id}/spells/{spell_id}/prepare`,
  `POST /{id}/spells/{spell_id}/unprepare`.
- `api/details/` (tag `Character Details`, read-only): `GET /{id}/classes`, `GET /{id}/feats`,
  `GET /{id}/features`, `GET /{id}/languages`, `GET /{id}/optional-features`,
  `GET /{id}/proficiencies`, `GET /{id}/senses`, `GET /{id}/resources`, `GET /{id}/choices`
  (the last reads already-*resolved* choices - not the same as the builder's own
  `GET /{id}/builder/choices`, which lists outstanding ones still to be made).

All of the above are implemented (real persistence via `services/`, `ModelSchema` responses in
`apps/characters/schemas.py`). `sheet` aggregates every collection a character owns into one
response (`CharacterSheetSchema`) - it deliberately does **not** compute AC/HP-max-derivation/
initiative/passive Perception/etc., since those need rules resolution that doesn't exist yet
(see `apps/builder/`); it's everything already *persisted*, not a finished character sheet.

`apps/characters/api/router.py` combines the four tag routers into the one router mounted in
`config/urls.py`.

**Services** (`apps/characters/services/`, one file per domain): `character.py` (CRUD + the
sheet aggregator), `classes.py`, `feats.py`, `features.py`, `languages.py`,
`optional_features.py`, `proficiencies.py`, `senses.py`, `resources.py`, `choices.py`,
`inventory.py`, `currency.py`, `spells.py`.

### `apps/builder/` — character creation/leveling engine

The D&D character engine: what can be chosen, whether a choice is valid, what it grants, and how
leveling up works. Mounted under `/api/characters` too, since its routes nest under
`/characters/{id}/builder/...` — it's logic bolted onto a `characters` resource, not a separate
top-level resource. Owns little to no persistent state of its own; it reads/writes `characters`
models by applying `rules` data.

Unlike `rules`/`characters`, this app's endpoints are still unimplemented stubs. It's not an
oversight - `rules`/`characters` are "implement the obvious CRUD/lookup for a fully-defined
model" work, while builder is an actual rules engine (multiclass spell-slot math, per-class
choice validation, prerequisite checking, ...) that needs its own deliberate design pass before
writing endpoint bodies would mean anything.

**API** (`apps/builder/api/`), three tag folders, one file per endpoint:

- `api/builder/` (tag `Character Builder`): `GET /{id}/builder`, `GET /{id}/builder/choices`,
  `GET /{id}/builder/choices/{key}`, `PUT /{id}/builder/choices/{key}`,
  `POST /{id}/builder/class`, `POST /{id}/builder/background`, `POST /{id}/builder/species`,
  `GET /{id}/builder/ability-options`, `PUT /{id}/builder/ability-scores`,
  `GET /{id}/builder/starting-equipment`, `POST /{id}/builder/starting-equipment`,
  `POST /{id}/builder/finalize`.
- `api/validation/` (tag `Character Validation`): `GET /{id}/builder/validation`,
  `POST /{id}/builder/validate` — returns structured errors (`path`/`code`/`message`) so the
  frontend never has to duplicate rules knowledge.
- `api/progression/` (tag `Character Progression`): `GET /{id}/builder/level-up`,
  `POST /{id}/builder/level-up/preview`, `POST /{id}/builder/level-up/commit`.

**Services** (`apps/builder/services/`, currently docstring-only placeholders, one file per
concern as laid out in the design doc):

| File | Will hold |
|---|---|
| `builder.py` | `BuilderService.get_state(character)` — the central state aggregator the whole builder API is built around |
| `choices.py` | Resolving/validating individual builder choices |
| `validation.py` | Whole-character validation (what's missing/invalid) |
| `prerequisites.py` | Prerequisite checks for feats/features/choices |
| `progression.py` | Level-up preview/commit logic |
| `effects.py` | Applying `rules.Effect` grants onto a character |
| `derived_stats.py` | Computing derived statistics (AC, HP, saves, etc.) |

**Resolvers** (`apps/builder/resolvers/`, currently docstring-only placeholders) — each knows how
one `rules` concept translates into grants on a character: `class_.py`, `species.py`,
`background.py`, `feat.py`, `equipment.py`, `spell.py`, `proficiency.py`.

**Schemas** (`apps/builder/schemas.py`) — currently a single placeholder file; will hold the
Ninja schemas for builder state/choices/validation/progression responses once the services exist.

### `apps/frontend/` — PWA shell

Not part of the `rules`/`characters`/`builder` layering above (it's the web UI, not game logic).
A minimal Django app serving server-rendered pages, wired up as an installable PWA via
`django-pwa`.

**Navigation shell** — every page (`templates/frontend/base.html`, extended by the rest) has a
header with a back button (omitted on `index`), the current page's title (just the app name on
`index` itself), and one language-toggle button that switches to the *other* language, labeled
with that language's own autonym (e.g. shows "Italiano" while browsing in English). Responsive,
mobile-first CSS with a dark-mode variant; a JS-measured `--app-height` custom property works
around mobile browsers resizing the visible viewport as the address bar shows/hides.

- `GET /` (`index`) — three full-height nav buttons: **Characters** → `/characters/`,
  **Handbook** → `/handbook/`, **World** → `/world/`. Characters is still a placeholder
  "coming soon" page (`overview.html`); **Handbook and World are both built out** (see below).
- `GET /handbook/` (`handbook_overview`) lists every `rules.HandbookSection` (a `list_page` like
  World's catalogs, but its back button returns to `index`, not `world-overview` - it's a
  sibling of World, not nested under it) - 12 rows (15 minus the 3 with no Italian text, see
[Internationalization](#internationalization-i18n)), since the single source chapter is flattened
  one level into one row per named topic rather than modeled as its own grouping (see
  `HandbookSection`'s docstring for why). Each links to `GET /handbook/<id>/`
  (`handbook_section_detail`), which renders exactly like a `Rule`/`Feat`/`Spell` detail page -
  one open "Description" section, no per-page collapsing needed now that each page covers one
  topic instead of the whole chapter.
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
  - There's no standalone browsing list for `rules.Rule` - `world/rules/<slug>/` exists purely
    as the landing page for `{@variantrule ...}` links found in other pages' text, so its back
    button returns to the World hub rather than to any specific list.
- `/manifest.json` and `/serviceworker.js` are served by `django-pwa` (`pwa` in
  `INSTALLED_APPS`, `path("", include("pwa.urls"))` in `config/urls.py`). Config lives in
  `config/settings.py` (`PWA_APP_*` / `PWA_SERVICE_WORKER_PATH`).
- The service worker itself is a real file at `static/js/serviceworker.js` (network-first for
  same-origin requests, falling back to cache only when offline - a stale cached page would
  otherwise silently ignore a language switch; explicitly never caches `/api/*`, since a stale
  API response would be actively misleading, unlike a stale static page).
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
when that translation is empty (`MODELTRANSLATION_FALLBACK_LANGUAGES`). Services, API schemas and
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
`{@tag ...}` markup is mirrored from the English text with the *English* lookup key kept and the
Italian wording in the display slot - `{@skill Perception|XPHB|Percezione}`,
`{@area Combattimento|06b|x}` - so the reference linker (which matches English catalog names)
still resolves them.

**The handbook shows the same content in both languages.** It's translated from the Italian SRD
5.2.1 (`IT_SRD_CC_v5.2.1.md`) plus `missing_text.md`, which covers everything the SRD chapter
has; what neither has - the chapter intro, "Rules Glossary", "Player or DM?", the three worked
examples and two small boxes - is listed in `OMITTED_ROW_IDS` / `OMITTED_BLOCK_IDS` in
`handbook_source.py` and dropped from the *English* handbook as well, at import time
(`db/handbook.json` is never edited), rather than Italian pages showing English text. To bring a
part back: translate it in `db/it/handbook.json`, take its id off the omit list, and re-run
`import_translations`. A test guarantees no English text survives in the Italian handbook. (The
model-level English fallback still exists for any future translated field that's only partly
filled in.) `{@dc 10}` renders "DC 10" / "CD 10" via `gettext`.

**The other catalogs** (`Spell`, `Feat`, `Rule`, `Species`, `Background`, `Class`, `Subclass`,
`Feature`, `Equipment`, ... - all registered in `apps/rules/translation.py`) work the same way but,
unlike the handbook, **nothing is removed for lacking Italian text**: a row or a part with no
translation keeps showing its English, so these pages can be partly Italian. Each has a file
`db/it/<model>.json` (`{row id: {field: overlay}}`, same overlay format), loaded by
`apps/rules/translation_sync.py` (`TRANSLATED_CATALOGS` maps model -> file -> fields) at the end of
`import_rules_data` and by `import_translations`. Search matches either language's name, and
`{@tag}` lookups use each row's English name (`name_en`), so links still resolve when the display
**Filled so far** (from `IT_SRD_CC_v5.2.1.md`): all 17 SRD feats; 335 of the 339 SRD spells
(their names; 288 with full text - the rest differ structurally from the English text or lost their
body in the SRD extraction, so they show an Italian name over English text); 101 of the 114 rules;
all 12 classes (name, blurb, "subclass" title), their 12 SRD subclasses, and about 230 class,
subclass, species-trait and feat features; the 9 SRD species (plus Italian blurbs for all 11); the
4 SRD backgrounds; and 207 of the 217 equipment items (name for all; full text for about 85 - the
tools and gear whose description block aligned). Class and subclass *features* that the SRD lists
differently from the English data (option rows, repeated "Ability Score Improvement" levels,
features with big embedded tables) keep their English text. **Not yet filled** (their columns exist
and fall back to English): skills, senses, languages, masteries, abilities, weapon properties,
optional features, the non-SRD rows, and the UI-side rendering of *measurements* and structured
values (feet, "1 action", size/creature-type codes, class-table column headers), which is still
English. The extraction was done with throwaway scripts (paragraph-by-paragraph alignment of the
Italian markdown to the English `entries` tree, tags mirrored by an English-to-Italian term
dictionary); rows that didn't align cleanly were left in English rather than guessed. English.

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

## Not in scope (per the architecture doc)

No `users` app, no auth, no combat system.

## Other files in this repo

`db/*.json` (plus their `*_schema.json` siblings) is the XPHB content dump the `rules` models
above are sourced from — see [Model status](#model-status). `db_old/` is the previous (pre-2025)
dump, kept as a permanent snapshot rather than deleted - one field (`Spell.classes`/`subclasses`)
is still deliberately read from it at import time, since the current `db/` dropped that data with
no replacement; see [docs/data_migration_2025.md](docs/data_migration_2025.md). `glossary.md` and
`extract_from_json.py` are pre-existing reference material (Italian/English D&D terminology, and
whatever produced the `db/` dump) unrelated to this Django scaffold; they're left untouched for
now.

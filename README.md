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

| Model | Status | Source | Notes |
|---|---|---|---|
| `Rule` | Defined | `db/rules.json` | |
| `Skill` | Defined | `db/skills.json` | |
| `Sense` | Defined | `db/senses.json` | |
| `Mastery` | Defined | `db/masteries.json` | |
| `EquipmentProperty` | Defined | `db/equipment_properties.json` | |
| `Equipment` | Defined | `db/equipments.json` | Covers weapons/armor/gear/tools/instruments alike via `category` |
| `Species` | Defined | `db/species.json` | All 11 entries are imported, including the one non-XPHB one (`grung`, source VGM) - unlike `Subclass`/`Feature`/etc., nothing here is filtered by source |
| `Background` | Defined | `db/backgrounds.json` | |
| `Feat` | Defined | `db/feats.json` | |
| `Class` | Defined | `db/classes.json` | Core metadata + raw `features` text; the level-progression table is split into `ClassLevel` |
| `ClassLevel` | Defined | `db/classes.json` (`table` rows) | Columns differ per class (spell slots vs Rages vs ...), so kept as a verbatim `columns` JSON map rather than fixed fields |
| `Subclass` | Defined | `db/classes.json` (`subclasses`) | Only the 48 XPHB-sourced subclasses out of 182 total across all classes; the source gives subclasses no id/page/srd. `description` (flavor text) is split out of the granting level's features at import time — see [Known data-import issues](#known-data-import-issues) |
| `SubclassLevel` | Defined | `db/classes.json` (subclass `features`) | A pure level marker - no `features` field of its own; its features are the `Feature` rows FK'd back to it, not a duplicated JSON copy — see [Known data-import issues](#known-data-import-issues) |
| `Spell` | Defined | `db/spells.json` | `classes`/`subclasses` kept as plain JSON lists, not FKs — see the model docstring |
| `Language` | Defined | `db/languages.json` | |
| `OptionalFeature` | Defined | `db/optional_features.json` | Not in the original architecture doc — covers Eldritch Invocations, Battle Master Maneuvers and Metamagic, which don't fit any existing catalog |
| `Proficiency` | Defined | `db/classes.json`, `db/backgrounds.json` | 85 rows: the flat comma-separated items in `Class.armor_proficiencies`/`weapon_proficiencies`/`tool_proficiencies` and `Background.skills`/`tools`, tagged with a `category` taken from which field they came from. The 2 items phrased as a choice instead of a flat grant (Bard's/Monk's `tool_proficiencies`) are excluded, not misfiled — see the model docstring |
| `Feature` | Defined | `db/classes.json`, `db/species.json`, `db/feats.json` | 665 rows: every explicitly named `{name, entries}` dict at the top level of `Class.features`, a subclass's per-level features, `Species.entries` and `Feat.entries` (bare prose strings mixed into those same lists are skipped, not renamed into features). Duplicates data still held verbatim on `Class`/`Species`/`Feat` — see the model docstring for why it isn't removed from them there; subclass features are the one exception, where `Feature` is the *only* copy — see [Known data-import issues](#known-data-import-issues) |
| `Effect` | Partly defined | derived from `Feature.entries` | 2094 rows: a mechanical index of literal 5etools inline tags (`{@damage ...}`, `{@condition ...}`, `{@dc ...}`, etc.) found anywhere in a `Feature`'s `entries` text, storing the tag name and raw tag text verbatim — not a semantic effects model, no tag is reinterpreted |
| `ChoiceDefinition` | Partly defined | `db/backgrounds.json`, `db/classes.json` | 27 rows, only where the source is reliably pattern-shaped: all 16 `Background.ability_scores` ("Choose from A, B, C") and 11 of 12 classes' `Class.proficiencies` "Skills: choose N from ..." clause (Bard's is genuinely empty in the source). Everything else that reads like a choice in the source (feat benefit prose, tool-proficiency choices) is inconsistent free text and was deliberately left unparsed |
| `HandbookSection` | Defined | `db/handbook.json` (`data`) | 15 rows: the source has exactly one chapter, so rather than model chapters as their own grouping, its root block and each of its direct named children ("Rules Glossary", "Player or DM?", "Dice", ...) are flattened into one row each - see the model docstring. `entries` holds each one's own content (arbitrarily nested headings/lists/tables/insets), rendered the same way as every other `entries`-shaped field. Surfaced two edge cases in `entries_render.py` itself - see [Known data-import issues](#known-data-import-issues), Issue 3 |

Every "Defined" model is loaded end-to-end (all 217 equipment rows, all 391 spells, all 12
classes × 20 levels, all 19 languages, all 58 optional features, etc. — no rows dropped or
truncated) by `manage.py import_rules_data` (`apps/rules/management/commands/`), which wipes
and reloads every `rules` table from `db/` in one transaction. `Proficiency`'s row count (85)
was independently cross-checked against a from-scratch recomputation; `Effect` and
`ChoiceDefinition` are "Partly defined" because they only cover the subset of their source
that's reliably, mechanically extractable — see their model docstrings for exactly what was
included and excluded, and why.

`Tool` and `SpellList`, both originally listed in architecture.md, were removed entirely (not
just left "Missing") once it was clear they'd always be pure duplicates: a Tool is just an
`Equipment` row with `category` in `{Tool, Artisan's Tools, Instrument, Gaming Set}`, and a
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

#### The general lesson, for next time

A model being "Defined" (mapped field-for-field) doesn't mean the source's own grouping is
semantically correct, or that nothing downstream of it is redundant:

- **Wrong grouping** (Issue 1): 5etools' JSON is authored for its own renderer, not for this
  schema, and a block that looks like "one feature with sub-details" can actually be "several
  features that got flavor text stapled to the first one." This tends to surface as something
  structurally *off* on a rendered page (not "missing data" but "correct data, wrong shape").
- **Redundant storage** (Issue 2): a field that exists only because *this project* built it
  (not a source-native field kept verbatim on purpose) is worth asking "does something else
  already hold this same data via a queryable relation?" - if so, the JSON copy is dead weight,
  not a deliberate tradeoff.
- **Untested rendering assumptions** (Issue 3): the generic renderer's rules (which tag
  convention applies, what shape a list item has) were each derived from - and only checked
  against - the handful of `db/*.json` files that existed when they were written. A new file
  large and varied enough (a whole handbook chapter, not one catalog entry) can exercise a shape
  none of those checks ever saw, and the failure is silent (no error, no missing row) - only
  visible by actually reading the rendered output.

Either way, the same discipline applies: don't fix the one example that prompted the question -
*verify the fix's assumption against every occurrence in `db/`* (a small Python script over
`db/*.json`, not just one subclass or one passage) before changing the import command or the
renderer, the way all three issues above were checked against every subclass/tag/list-item in
`db/`, not just the one Monk/Cleric/D20-Tests example that surfaced each. `Species`, `Feat`, and
`OptionalFeature` all have similarly-shaped `{name, entries}` source lists and haven't been
audited for the Issue 1/2 patterns - they're plausible places to look next.

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
| `Feat` | A feat (e.g. Alert, Tough) |
| `Class` | A character class (e.g. Fighter, Wizard) |
| `ClassLevel` | The per-level progression row for a `Class` |
| `Subclass` | A subclass/archetype of a `Class` |
| `SubclassLevel` | The per-level progression row for a `Subclass` |
| `Equipment` | An item of equipment (weapon, armor, gear, tool, instrument, ...) |
| `EquipmentProperty` | A property attached to `Equipment` (e.g. Finesse) |
| `Mastery` | A weapon mastery property |
| `Skill` | A skill (e.g. Athletics, Perception) |
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
  sibling of World, not nested under it) - 15 rows, since the single source chapter is flattened
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
  - `Species.entries` (traits) and `Class.features` (per-level features) get extra treatment
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

**This is a different problem from translating game content** (spell names, feat text, etc. in
`rules`) if that's ever wanted - that data is bulk-imported per-row from `db/`, not
developer-authored strings, so `gettext` is the wrong tool for it; a per-model-field approach
(e.g. `django-modeltranslation`, or extra `_it` columns) would fit better. Not needed today
since `rules` content is English-only for now - noting it so the two problems aren't conflated
later.

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
above are sourced from — see [Model status](#model-status). `glossary.md` and
`extract_from_json.py` are pre-existing reference material (Italian/English D&D terminology, and
whatever produced the `db/` dump) unrelated to this Django scaffold; they're left untouched for
now.

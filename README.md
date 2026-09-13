# la-compagna-del-gobbo

A D&D 5.5e (2024 rules) backend for player logic: characters, character creation/leveling, and the
static rules catalog they're built from.

See [architecture.md](architecture.md) for the full design rationale. This README documents what
exists today and what each placeholder is reserved for.

## Tech stack

- **Django** — models and persistence
- **Django Ninja** — the HTTP API (OpenAPI schema at `/api/docs`)
- **uvicorn** — ASGI server
- **uv** — dependency management
- **pytest** / **pytest-django** — tests
- **ruff** — linting and formatting

## Running it

```bash
uv run python manage.py migrate
uv run uvicorn config.asgi:application --reload
```

API docs: `http://192.168.1.72:3000/api/docs`

```bash
uv run pytest
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
- **No business logic in routers.** Endpoint functions call into `services/`. Right now the
  endpoints and services are empty placeholders (see below) — the wiring between them will be
  added alongside the model fields.
- **`rules` is read-only from the API's point of view.** It's populated via fixtures/importers/
  admin, not through write endpoints.

## App boundaries

Three Django apps, each owning a distinct layer:

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
| `Species` | Defined | `db/species.json` | One non-XPHB entry (`grung`, source VGM) exists in the file and is simply not imported |
| `Background` | Defined | `db/backgrounds.json` | |
| `Feat` | Defined | `db/feats.json` | |
| `Class` | Defined | `db/classes.json` | Core metadata + raw `features` text; the level-progression table is split into `ClassLevel` |
| `ClassLevel` | Defined | `db/classes.json` (`table` rows) | Columns differ per class (spell slots vs Rages vs ...), so kept as a verbatim `columns` JSON map rather than fixed fields |
| `Subclass` | Defined | `db/classes.json` (`subclasses`) | Only the 48 XPHB-sourced subclasses out of 182 total across all classes; the source gives subclasses no id/page/srd |
| `SubclassLevel` | Defined | `db/classes.json` (subclass `features`) | Grouped by level (a few subclasses grant 2 features at the same level) |
| `Spell` | Defined | `db/spells.json` | `classes`/`subclasses` kept as plain JSON lists, not FKs — see the model docstring |
| `Language` | Defined | `db/languages.json` | |
| `OptionalFeature` | Defined | `db/optional_features.json` | Not in the original architecture doc — covers Eldritch Invocations, Battle Master Maneuvers and Metamagic, which don't fit any existing catalog |
| `Proficiency` | Defined | `db/classes.json`, `db/backgrounds.json` | 85 rows: the flat comma-separated items in `Class.armor_proficiencies`/`weapon_proficiencies`/`tool_proficiencies` and `Background.skills`/`tools`, tagged with a `category` taken from which field they came from. The 2 items phrased as a choice instead of a flat grant (Bard's/Monk's `tool_proficiencies`) are excluded, not misfiled — see the model docstring |
| `Feature` | Defined | `db/classes.json`, `db/species.json`, `db/feats.json` | 611 rows: every explicitly named `{name, entries}` dict at the top level of `Class.features`, `SubclassLevel.features`, `Species.entries` and `Feat.entries` (bare prose strings mixed into those same lists are skipped, not renamed into features). Duplicates data still held verbatim on those parents — see the model docstring for why it isn't removed from them |
| `Effect` | Partly defined | derived from `Feature.entries` | 2142 rows: a mechanical index of literal 5etools inline tags (`{@damage ...}`, `{@condition ...}`, `{@dc ...}`, etc.) found anywhere in a `Feature`'s `entries` text, storing the tag name and raw tag text verbatim — not a semantic effects model, no tag is reinterpreted |
| `ChoiceDefinition` | Partly defined | `db/backgrounds.json`, `db/classes.json` | 27 rows, only where the source is reliably pattern-shaped: all 16 `Background.ability_scores` ("Choose from A, B, C") and 11 of 12 classes' `Class.proficiencies` "Skills: choose N from ..." clause (Bard's is genuinely empty in the source). Everything else that reads like a choice in the source (feat benefit prose, tool-proficiency choices) is inconsistent free text and was deliberately left unparsed |

Every "Defined" model was verified by loading its entire source file into the database once (all
217 equipment rows, all 391 spells, all 12 classes × 20 levels, all 19 languages, all 58 optional
features, etc. — no rows dropped or truncated). That was a one-off smoke test, not a saved
script; there's no fixture/import command yet (see the `services`/`api` placeholders above).
`Proficiency` and `Feature` were verified the same way against an independently-computed expected
row count (85 and 611 respectively); `Effect` and `ChoiceDefinition` are "Partly defined" because
they only cover the subset of their source that's reliably, mechanically extractable — see their
model docstrings for exactly what was included and excluded, and why.

`Tool` and `SpellList`, both originally listed in architecture.md, were removed entirely (not
just left "Missing") once it was clear they'd always be pure duplicates: a Tool is just an
`Equipment` row with `category` in `{Tool, Artisan's Tools, Instrument, Gaming Set}`, and a
class's spell list is just `Spell.classes`/`Spell.subclasses` filtered — a dedicated table would
carry the same rows twice with no independent reason to exist.

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

**API** (`apps/rules/api/rules/`, tag `Rules`, mounted at `/api/rules`) — one file per endpoint,
all currently stub handlers with no body logic:

`GET /classes`, `GET /classes/{id}`, `GET /classes/{id}/levels`, `GET /classes/{id}/subclasses`,
`GET /subclasses`, `GET /subclasses/{id}`, `GET /species`, `GET /species/{id}`,
`GET /backgrounds`, `GET /backgrounds/{id}`, `GET /feats`, `GET /feats/{id}`,
`GET /features`, `GET /features/{id}`, `GET /equipment`, `GET /equipment/{id}`,
`GET /equipment-properties`, `GET /masteries`, `GET /skills`, `GET /senses`,
`GET /languages`, `GET /tools`, `GET /proficiencies`, `GET /spells`, `GET /spells/{id}`,
`GET /rules`, `GET /rules/{key}`

Future filters mentioned in the design doc (`?class=wizard&level=3`, `?category=weapon`, etc.)
will be added once the models have fields.

**Services** (`apps/rules/services/`, one file per resource domain, currently docstring-only
placeholders): `class_.py`, `subclass.py`, `species.py`, `background.py`, `feat.py`, `feature.py`,
`equipment.py`, `skill.py`, `sense.py`, `language.py`, `tool.py`, `proficiency.py`, `spell.py`,
`rule.py` — will hold the list/get lookups the API endpoints delegate to.

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
  `DELETE /{id}`, `GET /{id}/sheet` — the `sheet` endpoint will return the fully resolved
  character (abilities, AC, HP, features, inventory, spells, ...) in one call.
- `api/inventory/` (tag `Character Inventory`): `GET /{id}/inventory`, `POST /{id}/inventory`,
  `PATCH /{id}/inventory/{item_id}`, `DELETE /{id}/inventory/{item_id}`,
  `POST /{id}/inventory/{item_id}/equip`, `POST /{id}/inventory/{item_id}/unequip`,
  `GET /{id}/currency`, `PATCH /{id}/currency`.
- `api/spells/` (tag `Character Spells`): `GET /{id}/spells`, `POST /{id}/spells`,
  `DELETE /{id}/spells/{spell_id}`, `POST /{id}/spells/{spell_id}/prepare`,
  `POST /{id}/spells/{spell_id}/unprepare`.
- `api/details/` (tag `Character Details`, read-only): `GET /{id}/features`,
  `GET /{id}/proficiencies`, `GET /{id}/senses`, `GET /{id}/resources`.

`apps/characters/api/router.py` combines the four tag routers into the one router mounted in
`config/urls.py`.

**Services** (`apps/characters/services/`, one file per domain, currently docstring-only
placeholders): `character.py`, `inventory.py`, `currency.py`, `spells.py`, `features.py`,
`proficiencies.py`, `senses.py`, `resources.py`.

**Open question, not yet decided:** *spending* a `CharacterResource` (using a Rage/Sorcery
Point/spell slot) and rest recovery (short/long rest restoring resources) don't clearly belong
to any of the three apps as currently scoped — `rules` is read-only, `builder` is creation/
leveling (not turn-by-turn play), and `characters` is passive state. A rest isn't combat (which
is explicitly out of scope), so this probably belongs in `characters` as a service function
mutating `CharacterResource.current_uses`, but that's a call worth making deliberately rather
than backing into.

### `apps/builder/` — character creation/leveling engine

The D&D character engine: what can be chosen, whether a choice is valid, what it grants, and how
leveling up works. Mounted under `/api/characters` too, since its routes nest under
`/characters/{id}/builder/...` — it's logic bolted onto a `characters` resource, not a separate
top-level resource. Owns little to no persistent state of its own; it reads/writes `characters`
models by applying `rules` data.

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

## Not in scope (per the architecture doc)

No `users` app, no auth, no combat system.

## Other files in this repo

`db/*.json` (plus their `*_schema.json` siblings) is the XPHB content dump the `rules` models
above are sourced from — see [Model status](#model-status). `glossary.md` and
`extract_from_json.py` are pre-existing reference material (Italian/English D&D terminology, and
whatever produced the `db/` dump) unrelated to this Django scaffold; they're left untouched for
now.

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

Every "Defined" model is loaded end-to-end (all 217 equipment rows, all 391 spells, all 12
classes × 20 levels, all 19 languages, all 58 optional features, etc. — no rows dropped or
truncated) by `manage.py import_rules_data` (`apps/rules/management/commands/`), which wipes
and reloads every `rules` table from `db/` in one transaction. `Proficiency` and `Feature`'s
row counts (85 and 611) were independently cross-checked against a from-scratch recomputation
before this command existed; `Effect` and `ChoiceDefinition` are "Partly defined" because they
only cover the subset of their source that's reliably, mechanically extractable — see their
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
  **Handbook** → `/handbook/`, **World** → `/world/`. Characters and Handbook are still
  placeholder "coming soon" pages (`overview.html`); **World is fully built out** (see below).
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

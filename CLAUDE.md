# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Django backend for D&D 5.5e (2024 rules) character play: static rules catalog, persisted
characters, and a (mostly unimplemented) character-builder engine. See [README.md](README.md)
for the full picture — tech stack, run modes, conventions, model status, and a detailed
per-app breakdown — and [architecture.md](architecture.md) for the original design rationale
(the README notes where the implementation has since diverged from it, e.g. `Tool`/`SpellList`
were dropped, several `Character*` models were added). Read the README before making
non-trivial changes; this file only adds what isn't there.

## Commands

Day-to-day dev loop (Postgres in Docker, Django on the host):

```bash
docker compose up -d dnd-db
export POSTGRES_HOST=localhost POSTGRES_PORT=5462   # matches docker-compose's port mapping
uv run python manage.py migrate
uv run python manage.py import_rules_data           # loads db/*.json into rules tables
uv run uvicorn config.asgi:application --reload
```

Tests and linting (same host env override — pytest-django creates its own throwaway DB):

```bash
POSTGRES_HOST=localhost POSTGRES_PORT=5462 uv run pytest
POSTGRES_HOST=localhost POSTGRES_PORT=5462 uv run pytest apps/rules/tests/test_services.py
POSTGRES_HOST=localhost POSTGRES_PORT=5462 uv run pytest apps/rules/tests/test_services.py::test_name -k pattern
uv run ruff check .
uv run ruff format .
```

`uv run python manage.py <command>` for anything else (`makemigrations`, `shell`, etc.).
`.env` (copied from `.env.dist`) supplies DB credentials to both `manage.py` and Docker Compose —
see the README's "Running it" section for exactly which vars to override for which run mode.

⚠️ `import_rules_data` wipes and reloads every `rules` table; it's a one-off/data-refresh step,
not part of the normal dev loop, and will raise `ProtectedError` once real `Character` rows
reference `rules` data.

**Redeploy after every task.** Once a task is finished (code changed and verified — tests pass,
`manage.py check` is clean), run `bash update-app.sh` from the repo root. It rebuilds the `dnd-web` image
from the working tree (every local change, committed or not - it does no `git pull`, so it needs
no GitHub credentials) and restarts only that container (`dnd-db` and its data are left
running). Do this automatically, without being asked, at the end of each task — not just when
explicitly told to deploy.

**Commit after every task.** Always commit the changes you make, automatically, at the end of
each task (after verifying and redeploying), without waiting to be asked. Local `git commit` only
- no push, since the sandbox may have no GitHub credentials.

## Architecture

Everything private is scoped by **campaign** (`apps/campaigns`: `Campaign`, `CampaignMembership` with
one DM per campaign, `CampaignInvite`; every `Character` and `LogEntry` has a `campaign`).
`apps/campaigns/services/membership.py` is the single place that decides who may see or manage
what; `characters/services/access.py` builds on it, and copy/transfer/leave live in
`characters/services/campaign_ops.py`. Never query `Character`/`LogEntry` for a page without
filtering by the current campaign (`apps/frontend/campaign_context.current`). In tests every new
user and character is put into one shared campaign automatically (`apps/conftest.py`); opt out with
`@pytest.mark.no_default_campaign`.

Three Django apps form a strict dependency chain — `rules` (static game content, read-only,
populated only via `import_rules_data`) → `characters` (persisted character state, FKs into
`rules`, no auth/ownership) → `builder` (creation/leveling engine, called directly by
the frontend; partly docstring-only services). A fourth
app, `frontend`, is the server-rendered PWA UI shell and sits outside this chain; `ai` (the
assistant chat: admin-managed LLM settings, request log, context builder) sits beside it. Full detail —
every model, per-app service/resolver breakdown — is in the README's "App
boundaries" section; don't re-derive it here, read that.

Two structural conventions apply across `rules`/`characters`/`builder`:

- **Models**: one file per model under `models/`, re-exported from `models/__init__.py`.
- **No API**: the app is deliberately a pure server-rendered frontend, exposed to the internet —
  there are no REST/JSON endpoints, no Django Ninja, no OpenAPI docs, and none should be added.
  The only HTTP surface is `apps/frontend/` views (plus `/i18n/`, PWA files; the few same-origin
  JSON action endpoints the UI's JS posts to, like `character_act` and the AI chat's `/chat/send/`, are not a public API); the Django admin is not installed. Views
  never contain business logic — that lives in `services/` (plain functions over
  querysets/instances, including any 404/validity checks), one file per domain.

`db/*.json` (with `*_schema.json` siblings) is the XPHB source data `rules` models are imported
from — see the README's "Model status" table before assuming a model or field exists; several
were deliberately left unparsed or dropped.

`apps/frontend/entries_render.py` renders the raw 5etools `entries` JSON blobs (used by several
`rules` models) into HTML, including resolving `{@variantrule ...}`/`{@spell ...}`/`{@feat ...}`
tags into real links — read it before touching how any catalog page's prose is displayed.

i18n uses Django's `gettext` framework (cookie-based `/i18n/setlang/`, not URL-prefixed) for
UI strings. `rules` game content is translated separately, with `django-modeltranslation`
(`_en`/`_it` columns on the existing tables, Italian text loaded from `db/it/*.json` by
`import_rules_data` / `import_translations`) - handbook, feats, spells and rules so far; see the README's
i18n section for the format and why the two are separate problems.

## Where spending lives

*Spending* a resource during play (HP, death saves, Hit Dice, spell slots, casting a spell, a
`CharacterResource`) and taking a **short/long rest** (per the SRD's Riposo breve/lungo) live in
`apps/characters/services/play.py`, called by the character sheet's `POST /characters/<id>/act/`
(see the README). `rules` stays read-only, `builder` stays creation/leveling. Not tracked, so not
handled: exhaustion, the 16 h between long rests (game time, not real time) and the timing of an
interrupted rest (the player says whether it was interrupted). Handled in `play.py`: reduced max HP /
ability scores (restored by a long rest), Arcane / Natural Recovery (slots back at a short rest, once per
long rest) and Natural Recovery's free Circle spell, and the long rest's one Weapon Mastery swap.

## Long-rest / rest logic not implemented yet

Done: Conditions and Exhaustion (`characters/conditions.py`: `Character.conditions`/`exhaustion`, a card on the Stats tab,
Exhaustion applied in `derived_stats`, a long rest -1, Tireless on a short rest), slots, Hit Dice, class-table resources and `FEATURE_RESOURCES` (`apps/builder/services/
feature_resources.py`), free casts, prepared-spell changes, the Weapon Mastery swap, Natural/Arcane
Recovery, and Circle of the Land's land (`services/land.py`). A long rest opens a *window* on the
character (`spell_changes`, `weapon_mastery_changes`, `rest_choices`) that a sheet control closes by
making the choice - copy that pattern for anything below: `play.long_rest()` opens it, a builder
service validates and applies it (builder, not `play`, if it needs `progression` helpers), a
`_act_*` in `character_sheet.py` exposes it, `_act_long_rest` prompts for it, and
`Character.rest_choices` (`{"key": True}`) is the generic flag. Not done:

- **Cantrip swap (Wizard, High Elf).** After a long rest a Wizard may replace one cantrip with
  another Wizard cantrip; a High Elf may replace the lineage's Prestidigitation with any Wizard
  cantrip. Plan: `rest_choices["cantrip"] = ["class:wizard", "species:elf"]` opened in
  `grant_rest_choices()` when the character has that class / the `high-elf` lineage; one swap per
  source. `change_cantrip(character, source, old, new)` deletes the `CharacterSpell` with that
  `source`/`spell` (level 0) and adds the new one with the same source via `update_or_create`
  (candidates: `class_spell_list`, level 0, not already known). A control in the Spellbook tab like
  the Weapon Mastery dialog.
- **Hunter's Prey (Hunter Ranger).** After a short *or* long rest the chosen option (Colossus
  Slayer / Horde Breaker) may be replaced. The choice is not stored yet, so first make it a
  `CharacterChoice` picked at level 3 (`lu.hunters_prey`, in `progression.plan`), then add
  `rest_choices["hunters_prey"]` from both `short_rest()` and `long_rest()`, and swap it like the land
  (a "Hunter's Prey (X)" feature per option, cut with the `lineage_features` helpers,
  `choice_option=True`).
- **Wild Shape known forms (Druid).** A long rest lets the Druid replace one known form. Not tracked
  (there is no bestiary); needs a free-text list on the sheet (`CharacterChoice` `class.wild_shape_forms`,
  list of strings) and a "replace one form" control opened by `rest_choices["wild_shape"]`.
- **Portent (Diviner) and Cosmic Omen (Circle of the Stars).** Rolled anew after every long rest:
  Portent is two d20s (three from level 14) the player spends to replace rolls; Cosmic Omen is one die,
  even = Weal, odd = Woe. Plan: `CharacterChoice` `rest.portent` = list of rolled values, rolled
  server-side in `grant_rest_choices()` (the old ones lost), shown on the Features tab with a
  "use" button that pops a value; Cosmic Omen stores the parity and shows which reaction applies.
- **Fast Crafting (Crafter feat).** After a long rest one piece of gear from the Fast Crafting table
  can be made; it falls apart after the next long rest. Plan: `rest_choices["fast_crafting"]`,
  picker over the table's items (the table is in the feat's `entries`, so it needs a small parsed
  list in `class_spec`-style data), and the item added to the inventory with `notes="fast crafting"`
  and removed by `long_rest()` before the new one.
- **Mystic Arcanum (Warlock 11/13/15/17).** One spell of level 6/7/8/9 each, cast once per long
  rest each. Plan: pick the spell at the level (`lu.arcanum`), store it as a `CharacterSpell`
  (`source="class:warlock:arcanum"`, level-keyed) and use the existing `free_cast_used` flag that
  `long_rest()` already clears, so casting it without a slot works like Magic Initiate's free cast.
- **Proficiency-bonus free casts (Forest Gnome's Speak with Animals, Fey Wanderer, ...).** The
  innate spell blocks with `"daily": {"pb": [...]}` get a single `free_cast_used` flag, but they may
  be cast PB times. Plan: give `CharacterSpell` a `free_casts_used` counter (migration) next to the
  flag, maximum from `tables.proficiency_bonus`, reset by `long_rest()`; `cast_spell()` increments it
  and `spell_row` in the sheet shows "n/PB".
- **The 16 hours between long rests / an interrupted rest.** Game time, not tracked; the player says
  whether a rest was interrupted. Leave it that way unless a clock is added to the sheet.

## Environment gotchas

Some sandboxes have no GitHub credentials wired up for network `git` operations - `git
pull`/`fetch`/`push` against the `origin` HTTPS remote fails with `fatal: could not read
Username for 'https://github.com'`, even though local commits/log/diff work fine. `update-app.sh`
doesn't touch the network, so redeploying still works there.

If `gettext`'s `msgfmt` isn't installable (no passwordless `sudo`, as in some sandboxes),
`locale/it/LC_MESSAGES/django.mo` can't be produced via `manage.py compilemessages`. Hand-compile
it with a small pure-Python script instead (don't commit the script — it's not project code).
The `.po`/`.mo` files themselves are completely standard; where `sudo apt install gettext` is
available, use the normal workflow: edit templates, `manage.py makemessages -l it`, fill in
`msgstr` lines, `manage.py compilemessages`.

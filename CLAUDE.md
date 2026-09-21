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

## Architecture

Three Django apps form a strict dependency chain — `rules` (static game content, read-only,
populated only via `import_rules_data`) → `characters` (persisted character state, FKs into
`rules`, no auth/ownership) → `builder` (creation/leveling engine, mounted under
`/characters/{id}/builder/...`, currently stub endpoints over docstring-only services). A fourth
app, `frontend`, is the server-rendered PWA UI shell and sits outside this chain. Full detail —
every model, every endpoint, per-app service/resolver breakdown — is in the README's "App
boundaries" section; don't re-derive it here, read that.

Two structural conventions apply across `rules`/`characters`/`builder`:

- **Models**: one file per model under `models/`, re-exported from `models/__init__.py`.
- **API**: one folder per Ninja tag group under `api/`, one file per endpoint, with the
  subfolder's `__init__.py` creating the shared `router = Router(tags=[...])` and importing
  every sibling endpoint module purely to trigger its `@router.<method>` registration
  (`apps/*/api/**/__init__.py` is ruff-exempted from E402/F401 for exactly this reason). Routers
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

*Spending* a resource during play (HP, death saves, Hit Dice, spell slots) lives in
`apps/characters/services/play.py`, called by the character sheet's `POST /characters/<id>/act/`
(see the README). `rules` stays read-only, `builder` stays creation/leveling. Not decided yet:
short/long **rests** restoring what is spent, and spending a `CharacterResource` (Rage, Sorcery
Points - the sheet doesn't show those); both would most naturally be more functions in `play.py`.

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

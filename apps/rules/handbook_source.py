"""Reads the handbook's source JSON into one dict per `HandbookSection` row - the English
`db/handbook.json`, and its Italian counterpart `db/it/handbook.json` merged onto it.

Shared by `import_rules_data` (wipe + reload, English and Italian together) and
`import_translations` (Italian only, into rows that already exist), so both see the same rows.

**`db/it/handbook.json` format.** A sparse overlay, keyed by `HandbookSection` id, mirroring the
English row's shape:

    {"095": {"name": "Danni e guarigione", "entries": [ ...translated tree... ]}}

Inside `entries` the tree has the same shape as the English one - same nesting, same list
positions, and each named block repeats its `id` so a misalignment fails loudly instead of
silently attaching text to the wrong block. Only translatable keys need appearing (`name`,
`entries`, `entry`, `items`, `rows`, `caption`, `colLabels`, ...); everything language-neutral
(`type`, `page`, `style`, `columns`, images, ...) is inherited from the English node. A `null`
anywhere means "not translated yet - keep the English here", and trailing `null`s may be left out,
so a partly translated section (this file only has the pages that were available so far) still
renders as one complete tree, English filling the gaps.

**Untranslated parts are dropped from both languages.** Whatever the Italian source doesn't have
(it comes from the SRD, which lacks e.g. the chapter intro and the worked examples) is listed in
`OMITTED_ROW_IDS` / `OMITTED_BLOCK_IDS` below and removed from the English handbook too, so the two
languages always show the same content instead of Italian pages falling back to English text. The
omit lists are the only place to touch: translate a part, take its id off the list, and it
reappears in both languages. `db/handbook.json` itself is never edited.

`{@tag ...}` markup in the Italian text mirrors the English tag, keeping the English lookup key and
putting the Italian wording in the display slot - `{@skill Perception|XPHB|Percezione}`,
`{@area Combattimento|06b|x}` - which is what `entries_render._tag_display_text()` shows and what
the reference linker still resolves by the English name.
"""

import json
from pathlib import Path

from django.conf import settings

DB_DIR = Path(settings.BASE_DIR) / "db"
ITALIAN_HANDBOOK = DB_DIR / "it" / "handbook.json"

#: Whole `HandbookSection` rows with no Italian text: the chapter root (its intro and example
#: dialogue), "Rules Glossary" and "Player or DM?".
OMITTED_ROW_IDS = {"007", "008", "009"}
#: Named blocks inside otherwise translated rows, with no Italian text: the three worked examples
#: (Exploration, Social Interaction, Combat and Damage - each with all its sidebars) and the
#: "Skills with Different Abilities" / "What Would Your Character Do?" boxes.
OMITTED_BLOCK_IDS = {"063", "046", "0b8", "03b", "042"}
#: English wording that pointed at an omitted block, rewritten so it doesn't dangle. Each must
#: match exactly once or the import fails - a changed source shouldn't silently skip a fix.
ENGLISH_TEXT_FIXES = {
    ', each of which is described in "{@area Social Interaction Example.|046|x}"': ".",
}


class TranslationDataError(ValueError):
    """The Italian file doesn't line up with the English source."""


def _load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def english_rows() -> list[dict]:
    """The English handbook, flattened one level into `HandbookSection`-shaped dicts
    (`id`, `name`, `page`, `entries`) - see `HandbookSection`'s docstring for why: the chapter's
    own root block becomes one row (its `entries` trimmed to just its own leading content, not the
    nested sections' content too, which becomes their own rows), and each of its direct named
    children ("Rules Glossary", "Player or DM?", "Dice", ...) becomes one more.

    db/handbook.json uses a top-level "data" key (one item per chapter), unlike every other
    db/*.json file's type-named key - a different dump format from a different source pass (see
    docs/data_migration_2025.md - this file is copied verbatim from db_old/, unchanged).
    """
    chapter = _load_json(DB_DIR / "handbook.json")["data"][0]
    leading_entries = [e for e in chapter["entries"] if not (isinstance(e, dict) and e.get("name"))]
    named_children = [e for e in chapter["entries"] if isinstance(e, dict) and e.get("name")]

    rows = [
        {
            "id": chapter["id"],
            "name": chapter["name"],
            "page": chapter["page"],
            "entries": leading_entries,
        }
    ]
    rows.extend(
        {
            "id": child["id"],
            "name": child["name"],
            "page": child["page"],
            "entries": child["entries"],
        }
        for child in named_children
    )
    return rows


def overlay_translation(english, italian, path: str = ""):
    """Return `english` with `italian` laid over it (see the module docstring for the rules).
    Raises `TranslationDataError`, naming the offending path, wherever the two don't line up.
    """
    if italian is None:
        return english

    if isinstance(english, dict):
        if not isinstance(italian, dict):
            raise TranslationDataError(f"{path}: expected an object, got {type(italian).__name__}")
        if "id" in italian and italian["id"] != english.get("id"):
            raise TranslationDataError(
                f"{path}: block id {italian['id']!r} doesn't match the English block "
                f"{english.get('id')!r} at this position"
            )
        merged = dict(english)
        for key, value in italian.items():
            if key == "id":
                continue
            if key not in english:
                raise TranslationDataError(f"{path}: {key!r} doesn't exist on the English block")
            merged[key] = overlay_translation(english[key], value, f"{path}.{key}")
        return merged

    if isinstance(english, list):
        if not isinstance(italian, list):
            raise TranslationDataError(f"{path}: expected a list, got {type(italian).__name__}")
        if len(italian) > len(english):
            raise TranslationDataError(
                f"{path}: {len(italian)} items, but the English list only has {len(english)}"
            )
        merged = list(english)
        for i, value in enumerate(italian):
            merged[i] = overlay_translation(english[i], value, f"{path}[{i}]")
        return merged

    if isinstance(english, str):
        if not isinstance(italian, str):
            raise TranslationDataError(f"{path}: expected text, got {type(italian).__name__}")
        return italian

    raise TranslationDataError(f"{path}: can't translate a {type(english).__name__} value")


def italian_rows(english: list[dict]) -> dict[str, dict]:
    """`{row id: {"name": str | None, "entries": list | None}}` for every row the Italian file
    covers - `entries` already merged onto the English tree, `None` where the file has no text for
    that field (so the column stays NULL and the site falls back to English wholesale). Empty when
    `db/it/handbook.json` doesn't exist.
    """
    if not ITALIAN_HANDBOOK.exists():
        return {}
    source = _load_json(ITALIAN_HANDBOOK)

    by_id = {row["id"]: row for row in english}
    unknown = sorted(set(source) - set(by_id))
    if unknown:
        raise TranslationDataError(f"db/it/handbook.json: unknown handbook section ids {unknown}")

    result = {}
    for row_id, translated in source.items():
        english_row = by_id[row_id]
        entries = translated.get("entries")
        result[row_id] = {
            "name": translated.get("name"),
            "entries": (
                overlay_translation(english_row["entries"], entries, f"{row_id}.entries")
                if entries is not None
                else None
            ),
        }
    return result


def _prune(node):
    """`node` without any block whose id is in `OMITTED_BLOCK_IDS`, at any depth."""
    if isinstance(node, list):
        return [
            _prune(item)
            for item in node
            if not (isinstance(item, dict) and item.get("id") in OMITTED_BLOCK_IDS)
        ]
    if isinstance(node, dict):
        return {key: _prune(value) for key, value in node.items()}
    return node


def _fix_english_text(node, applied: set):
    if isinstance(node, str):
        for old, new in ENGLISH_TEXT_FIXES.items():
            if old in node:
                applied.add(old)
                node = node.replace(old, new)
        return node
    if isinstance(node, list):
        return [_fix_english_text(item, applied) for item in node]
    if isinstance(node, dict):
        return {key: _fix_english_text(value, applied) for key, value in node.items()}
    return node


def load_handbook() -> tuple[list[dict], dict[str, dict]]:
    """`(english rows, {row id: italian fields})` exactly as they should be stored: the Italian
    overlay merged onto the *full* English tree first (so its list positions line up with the
    source), then the omitted rows/blocks pruned from both languages.
    """
    english = english_rows()
    italian = italian_rows(english)

    rows = []
    applied: set = set()
    for row in english:
        if row["id"] in OMITTED_ROW_IDS:
            continue
        rows.append({**row, "entries": _fix_english_text(_prune(row["entries"]), applied)})

    unused = set(ENGLISH_TEXT_FIXES) - applied
    if unused:
        raise TranslationDataError(f"English text fixes matched nothing: {sorted(unused)}")

    kept = {}
    for row_id, fields in italian.items():
        if row_id in OMITTED_ROW_IDS:
            continue
        entries = fields["entries"]
        kept[row_id] = {
            "name": fields["name"],
            "entries": _prune(entries) if entries is not None else None,
        }
    return rows, kept

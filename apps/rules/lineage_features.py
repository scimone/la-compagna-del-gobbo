"""The one-trait-per-lineage `Feature` rows of a species with a lineage choice.

A species like Elf carries a single trait, "Elven Lineage", whose text lists every lineage
(Drow/High Elf/Wood Elf) in a table. Once a player has picked one, their character should show
*that* lineage - "Elven Lineage (Wood Elf)", with only its own row - not the whole table. The
source's `_versions` do carry such a per-lineage text, but the importer keeps only their
structured data (see `Species.lineages`), so the text is cut from the generic trait here instead:
the same function runs over the English entries and the already-translated Italian ones, so both
languages come out of the same cut.
"""

import re

from django.utils.text import slugify

_TRAILING_PAREN = re.compile(r"\(([^()]+)\)\s*$")


def _blocks(entries: list | None, kind: str) -> dict | None:
    return next((e for e in entries or [] if isinstance(e, dict) and e.get("type") == kind), None)


def _list_item_index(items: list, lineage: dict) -> int | None:
    label = lineage["label"]
    for i, item in enumerate(items):
        name = item.get("name", "") if isinstance(item, dict) else ""
        if name == label or f"({label} Giant)" in name:
            return i
    return None


def lineage_feature(species_entries_en: list, species_entries_it: list | None, lineage: dict):
    """`(name_en, entries_en, name_it, entries_it)` for one lineage, or `None` when the generic
    trait it replaces has no table/list to cut it from. `entries_it` is an overlay of
    `entries_en` (see `handbook_source.overlay_translation`), `None` without Italian text."""
    index = next(
        (
            i
            for i, e in enumerate(species_entries_en)
            if isinstance(e, dict) and e.get("name") == lineage["replaces"]
        ),
        None,
    )
    if index is None:
        return None
    generic_en = species_entries_en[index]
    entries = generic_en.get("entries", [])
    generic_it = (
        species_entries_it[index]
        if species_entries_it and index < len(species_entries_it)
        else None
    )
    entries_it = (generic_it or {}).get("entries")
    paragraphs = [e for e in entries if isinstance(e, str)]
    name_en = f"{generic_en['name']} ({lineage['label']})"

    table = _blocks(entries, "table")
    if table is not None:
        row = next(
            (
                i
                for i, r in enumerate(table["rows"])
                if slugify(re.sub(r"\{@[^ ]+ ([^|}]+)[^}]*\}", r"\1", str(r[0]))) == lineage["key"]
            ),
            None,
        )
        if row is None:
            return None
        # The paragraph after the intro ("Choose a lineage ...") explains the level 3/5 spells;
        # only the spell-granting tables (4 columns) have one worth keeping.
        keep_paragraph = len(table["colLabels"]) > 2 and len(paragraphs) > 1
        cut = {k: v for k, v in table.items() if k not in ("caption", "rows")}
        out_en = [paragraphs[1]] if keep_paragraph else []
        out_en.append({**cut, "rows": [table["rows"][row]]})
        out_it = name_it = None
        table_it = _blocks(entries_it, "table")
        if table_it and row < len(table_it.get("rows", [])):
            para_it = [e for e in entries_it if isinstance(e, str)]
            out_it = []
            if keep_paragraph:
                out_it.append(para_it[1] if len(para_it) > 1 else None)
            out_it.append({"colLabels": table_it["colLabels"], "rows": [table_it["rows"][row]]})
            name_it = f"{generic_it['name']} ({table_it['rows'][row][0]})"
        return name_en, out_en, name_it, out_it

    lst = _blocks(entries, "list")
    if lst is None:
        return None
    item = _list_item_index(lst["items"], lineage)
    if item is None:
        return None
    out_en = [{**lst, "items": [lst["items"][item]]}]
    list_it = _blocks(entries_it, "list")
    out_it = name_it = None
    if list_it and item < len(list_it.get("items", [])):
        item_it = list_it["items"][item]
        out_it = [{"items": [item_it]}]
        match = _TRAILING_PAREN.search(item_it.get("name", ""))
        name_it = f"{generic_it['name']} ({match.group(1) if match else item_it['name']})"
    return name_en, out_en, name_it, out_it

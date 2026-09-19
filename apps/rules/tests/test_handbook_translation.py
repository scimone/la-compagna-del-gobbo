import json
import re
from collections import Counter

import pytest
from django.core.management import call_command
from django.utils import translation

from apps.rules.handbook_source import (
    ITALIAN_HANDBOOK,
    OMITTED_BLOCK_IDS,
    OMITTED_ROW_IDS,
    TranslationDataError,
    english_rows,
    italian_rows,
    load_handbook,
    overlay_translation,
)
from apps.rules.management.commands.import_rules_data import Command as ImportCommand
from apps.rules.models import HandbookSection, Spell

TAG = re.compile(r"\{@(\w+)\s+([^}]*)\}")


# --- overlay_translation -----------------------------------------------------------------


def test_overlay_none_keeps_english():
    assert overlay_translation({"name": "Hiding"}, None) == {"name": "Hiding"}


def test_overlay_inherits_language_neutral_keys():
    english = {"type": "entries", "id": "054", "name": "Hiding", "entries": ["Hide."]}
    italian = {"id": "054", "name": "Nascondersi", "entries": ["Nasconditi."]}
    assert overlay_translation(english, italian) == {
        "type": "entries",
        "id": "054",
        "name": "Nascondersi",
        "entries": ["Nasconditi."],
    }


def test_overlay_null_and_omitted_trailing_items_fall_back_to_english():
    assert overlay_translation(["one", "two", "three"], [None, "due"]) == ["one", "due", "three"]


def test_overlay_id_mismatch_names_the_path():
    with pytest.raises(TranslationDataError, match=r"\.entries\[0\].*'999'"):
        overlay_translation(
            {"entries": [{"id": "054", "name": "Hiding"}]},
            {"entries": [{"id": "999", "name": "Nascondersi"}]},
        )


@pytest.mark.parametrize(
    ("english", "italian"),
    [
        (["a"], ["a", "b"]),  # longer than the English list
        ({"name": "A"}, {"nam": "A"}),  # key that isn't on the English block
        ("text", ["text"]),  # wrong shape
        (["a"], "a"),
    ],
)
def test_overlay_rejects_misaligned_data(english, italian):
    with pytest.raises(TranslationDataError):
        overlay_translation(english, italian)


# --- the real db/it/handbook.json --------------------------------------------------------


def _string_pairs(english, italian, path):
    if italian is None:
        return
    if isinstance(english, dict):
        for key, value in italian.items():
            if key != "id":
                yield from _string_pairs(english[key], value, f"{path}.{key}")
    elif isinstance(english, list) and path.endswith(".items") and _all_strings(english):
        # A plain list of references (senses, hazards, conditions) may be alphabetised in
        # Italian, so its entries are compared as a whole instead of position by position.
        yield path, "\n".join(english), "\n".join(italian)
    elif isinstance(english, list):
        for i, value in enumerate(italian):
            yield from _string_pairs(english[i], value, f"{path}[{i}]")
    else:
        yield path, english, italian


def _all_strings(values):
    return all(isinstance(value, str) for value in values)


def _tags(text):
    tags = Counter()
    for match in TAG.finditer(text):
        tag, body = match.group(1), match.group(2)
        if tag in ("b", "i"):  # bare styling, no reference to keep - the wording is translated
            continue
        segments = body.split("|")
        # The English lookup key is what must survive translation: the id for `area`, the whole
        # value for `dc`/`dice`, the first segment (the English name) for everything else.
        key = segments[1] if tag == "area" else body if tag in ("dc", "dice") else segments[0]
        tags[(tag, key.lower())] += 1
    return tags


def test_italian_handbook_file_lines_up_with_the_english_source():
    english = english_rows()
    italian = italian_rows(english)  # raises if any id/shape is off

    assert {"00c", "00e", "011", "01c", "01f", "036", "03e", "043", "04b"} <= set(italian)
    assert {"06b", "095", "0b5"} <= set(italian)
    assert italian["06b"]["name"] == "Combattimento"


def test_italian_handbook_tags_mirror_the_english_tags():
    english_by_id = {row["id"]: row for row in english_rows()}
    raw = json.loads(ITALIAN_HANDBOOK.read_text(encoding="utf-8"))

    mismatches = []
    for row_id, translated in raw.items():
        english_row = english_by_id[row_id]
        for path, en, it in _string_pairs(english_row, translated, row_id):
            if _tags(en) != _tags(it):
                mismatches.append(path)

    # The Italian text has no "Social Interaction Example" (it isn't in the SRD), so the
    # Roleplaying paragraph that points readers to it loses that one cross-reference.
    assert mismatches == ["043.entries[4].entries[1]"]


# --- HandbookSection language fallback ----------------------------------------------------


@pytest.mark.django_db
def test_section_reads_in_the_active_language_and_falls_back_to_english():
    HandbookSection.objects.create(
        id="x1",
        page=1,
        name_en="Hiding",
        name_it="Nascondersi",
        entries_en=["Hide."],
        entries_it=["Nasconditi."],
    )
    HandbookSection.objects.create(id="x2", page=1, name_en="Dice", entries_en=["Roll."])

    with translation.override("it"):
        translated = HandbookSection.objects.get(pk="x1")
        untranslated = HandbookSection.objects.get(pk="x2")
        assert (translated.name, translated.entries) == ("Nascondersi", ["Nasconditi."])
        assert (untranslated.name, untranslated.entries) == ("Dice", ["Roll."])

    with translation.override("en"):
        assert HandbookSection.objects.get(pk="x1").name == "Hiding"


# --- what the handbook keeps: the same content in both languages -----------------------------

TRANSLATABLE_KEYS = ("name", "entries", "entry", "items", "rows", "caption", "colLabels")


def _english_leftovers(english, italian, path=""):
    """Paths of text that is still English in the Italian tree (identical wording, with some
    real words in it once `{@tag}` markup - which keeps its English lookup key - is set aside).
    """
    if isinstance(english, str):
        if english == italian and re.search(r"[A-Za-z]{4,}", TAG.sub("", english)):
            yield path
    elif isinstance(english, list):
        for i, (en, it) in enumerate(zip(english, italian, strict=True)):
            yield from _english_leftovers(en, it, f"{path}[{i}]")
    elif isinstance(english, dict) and english.get("type") not in ("image", "statblock"):
        for key in TRANSLATABLE_KEYS:
            if key in english:
                yield from _english_leftovers(english[key], italian[key], f"{path}.{key}")
        if "colLabelRows" in english:  # (the one table with a spanning header row)
            yield from _english_leftovers(
                english["colLabelRows"], italian["colLabelRows"], f"{path}.colLabelRows"
            )


def _block_ids(node):
    if isinstance(node, dict):
        if "id" in node:
            yield node["id"]
        for value in node.values():
            yield from _block_ids(value)
    elif isinstance(node, list):
        for item in node:
            yield from _block_ids(item)


def test_omitted_parts_are_gone_from_both_languages():
    rows, italian = load_handbook()

    assert not OMITTED_ROW_IDS & {row["id"] for row in rows}
    assert not OMITTED_ROW_IDS & set(italian)
    for row in rows:
        assert not OMITTED_BLOCK_IDS & set(_block_ids(row["entries"])), row["id"]
    for fields in italian.values():
        assert not OMITTED_BLOCK_IDS & set(_block_ids(fields["entries"]))


def test_no_english_text_is_left_in_the_italian_handbook():
    english, italian = load_handbook()

    leftovers = []
    for row in english:
        translated = italian[row["id"]]  # every kept row has Italian text
        assert translated["name"] and translated["name"] != row["name"]
        assert translated["entries"] is not None
        leftovers += _english_leftovers(row["entries"], translated["entries"], row["id"])

    assert leftovers == []


def test_english_wording_that_pointed_at_a_removed_example_is_trimmed():
    english, _italian = load_handbook()
    social = next(row for row in english if row["id"] == "043")

    roleplaying = next(
        block for block in social["entries"] if isinstance(block, dict) and block.get("id") == "044"
    )
    assert roleplaying["entries"][1].endswith("or a descriptive approach.")


# --- importing ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_import_handbook_stores_both_languages_and_drops_the_omitted_rows():
    ImportCommand()._import_handbook()

    combat = HandbookSection.objects.get(pk="06b")
    assert combat.name_en == "Combat"
    assert combat.name_it == "Combattimento"
    assert not HandbookSection.objects.filter(pk__in=OMITTED_ROW_IDS).exists()
    assert not HandbookSection.objects.filter(name_it__isnull=True).exists()


@pytest.mark.django_db
def test_import_translations_syncs_rows_without_wiping_anything_else():
    call_command("import_rules_data")
    HandbookSection.objects.filter(pk="06b").delete()  # a row that went missing
    HandbookSection.objects.update(name_it=None, entries_it=None)  # Italian never loaded
    HandbookSection.objects.create(id="009", page=7, name_en="Player or DM?", entries_en=[])
    spells_before = Spell.objects.count()

    call_command("import_translations")

    combat = HandbookSection.objects.get(pk="06b")
    assert (combat.name_en, combat.name_it) == ("Combat", "Combattimento")
    assert not HandbookSection.objects.filter(pk="009").exists()  # stale row removed
    assert not HandbookSection.objects.filter(name_it__isnull=True).exists()
    assert Spell.objects.count() == spells_before  # other catalogs left in place

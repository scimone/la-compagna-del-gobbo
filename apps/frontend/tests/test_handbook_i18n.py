import pytest
from django.core.management import call_command

from apps.rules.management.commands.import_rules_data import Command as ImportCommand


@pytest.fixture
def handbook(db):
    ImportCommand()._import_handbook()


def _get(client, url, language):
    client.cookies["django_language"] = language
    return client.get(url).content.decode()


def test_handbook_section_renders_in_italian(client, handbook):
    html = _get(client, "/handbook/095/", "it")

    assert "Danni e guarigione" in html
    assert "Tiri salvezza contro morte" in html
    assert "Saggezza (Medicina) con CD 10" in html  # `{@dc 10}` reads "CD 10", not just "10"


def test_handbook_section_renders_in_english(client, handbook):
    html = _get(client, "/handbook/095/", "en")

    assert "Damage and Healing" in html
    assert "Death Saving Throws" in html
    assert "DC 10" in html


def test_sections_without_italian_text_are_not_served_in_either_language(client, handbook):
    for language in ("it", "en"):
        for section_id in ("007", "008", "009"):  # chapter intro, Rules Glossary, Player or DM?
            client.cookies["django_language"] = language
            assert client.get(f"/handbook/{section_id}/").status_code == 404


def test_handbook_overview_lists_the_same_sections_in_both_languages(client, handbook):
    italian = _get(client, "/handbook/", "it")
    english = _get(client, "/handbook/", "en")

    assert "Combattimento" in italian
    assert "Dadi" in italian
    assert "Combat" in english
    assert "Dice" in english
    for html in (italian, english):
        assert "Player or DM?" not in html
        assert "Rules Glossary" not in html


def test_worked_examples_are_removed_in_both_languages(client, handbook):
    for language in ("it", "en"):
        html = _get(client, "/handbook/043/", language)
        assert "Social Interaction Example" not in html
        assert "Ismark" not in html  # the example's dialogue


def test_skills_table_is_fully_translated(client, handbook):
    html = _get(client, "/handbook/036/", "it")

    assert "Acrobazia" in html
    assert "Furtività" in html
    assert "Sfuggi all&#x27;attenzione altrui" in html or "Sfuggi all'attenzione altrui" in html
    assert "Segui le tracce" in html


@pytest.fixture
def catalogs(db):
    call_command("import_rules_data")


def test_spell_page_and_english_name_search_work_from_the_italian_site(client, catalogs):
    page = _get(client, "/world/spells/fireball/", "it")
    assert "Palla di fuoco" in page

    found = _get(client, "/world/spells/?q=Fireball", "it")  # English name, Italian site
    assert "Palla di fuoco" in found
    found = _get(client, "/world/spells/?q=palla", "en")  # Italian name, English site
    assert "Fireball" in found


def test_class_and_species_pages_render_in_italian(client, catalogs):
    assert "Barbaro" in _get(client, "/world/classes/barbarian/", "it")
    assert "Ira" in _get(client, "/world/classes/barbarian/?tab=levels", "it")
    assert "Dragonide" in _get(client, "/world/species/dragonborn/", "it")
    assert "Scurovisione" in _get(client, "/world/species/dragonborn/?tab=traits", "it")


def test_class_level_table_headers_and_units_are_translated_in_italian(client, catalogs):
    html = _get(client, "/world/classes/monk/", "it")

    # column headers translated from the source's English column names
    assert "Punti concentrazione" in html
    assert "Arti marziali" in html
    assert "Movimento senza armatura" in html
    # a Monk's Unarmored Movement bonus (feet in the source) shows in meters
    assert "+3 m" in html  # level 2: +10 ft.
    assert "+4,5 m" in html  # level 6: +15 ft.
    assert "+10 ft." not in html
    assert "+15 ft." not in html


def test_class_level_table_stays_imperial_in_english(client, catalogs):
    html = _get(client, "/world/classes/monk/", "en")

    assert "Unarmored Movement" in html
    assert "+10 ft." in html
    assert "Punti concentrazione" not in html


def test_species_speed_and_darkvision_show_in_metres_on_the_italian_site(client, catalogs):
    html = _get(client, "/world/species/elf/", "it")
    assert "9 m" in html
    assert "30 ft." not in html

    html = _get(client, "/world/species/dwarf/", "it")
    assert "36 m" in html  # Darkvision 120 ft.


def test_species_speed_and_darkvision_stay_imperial_in_english(client, catalogs):
    html = _get(client, "/world/species/elf/", "en")
    assert "30 ft." in html


def test_spell_range_shows_in_metric_on_the_italian_site(client, catalogs):
    # Fireball's range is 150 feet in the source
    html = _get(client, "/world/spells/fireball/", "it")
    assert "45 metri" in html
    assert "150 feet" not in html

    html = _get(client, "/world/spells/fireball/", "en")
    assert "150 feet" in html


def test_spell_range_filter_shows_metric_labels_on_the_italian_site(client, catalogs):
    html = _get(client, "/world/spells/", "it")
    assert "45 metri" in html

    html = _get(client, "/world/spells/", "en")
    assert "150 feet" in html


def test_english_fallback_text_shows_metric_measurements_on_the_italian_site(client, catalogs):
    # Thorn Whip has no Italian text yet (falls back to English); its body still mentions a
    # distance ("10 feet"), which should read metric even though the sentence stays English.
    html = _get(client, "/world/spells/thorn-whip/", "it")
    assert "3 meters" in html
    assert "10 feet" not in html

    html = _get(client, "/world/spells/thorn-whip/", "en")
    assert "10 feet" in html

"""Glossary rules whose official Italian text had holes (English left showing on the Italian
site), filled in by hand in `db/it/rules.json` and badged "Traduzione"."""

import re

import pytest

from apps.rules.management.commands.import_rules_data import Command as ImportCommand
from apps.rules.models import Rule
from apps.rules.translation_sync import TRANSLATED_CATALOGS, sync_catalog


@pytest.fixture
def imported(db):
    ImportCommand()._import_rules()
    sync_catalog(Rule, *TRANSLATED_CATALOGS[Rule])


def _page(client, slug, language):
    client.cookies["django_language"] = language
    html = client.get(f"/world/rules/{slug}/").content.decode()
    return html.split("<main>", 1)[1].split("</main>", 1)[0]


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _badged_headings(html):
    return re.findall(r'<h3>([^<]*?)\s*<span class="self-translated-badge"', html)


@pytest.mark.parametrize("slug", ["action", "area-of-effect", "condition"])
def test_rules_with_a_missing_intro_and_list_are_translated_and_badged_on_the_description(
    client, imported, slug
):
    italian = _page(client, slug, "it")

    assert 'Descrizione <span class="self-translated-badge"' in italian
    assert "This glossary" not in italian and "On your turn" not in italian
    assert "The descriptions of many spells" not in italian
    # the badge is Italian-only
    assert "self-translated-badge" not in _page(client, slug, "en")


def test_action_lists_the_twelve_actions_in_italian(client, imported):
    text = _text(_page(client, "action", "it"))

    for name in (
        "Aiuto Attacco Disimpegno Influenza Magia Nascondersi Prepararsi Ricerca Scatto "
        "Schivata Studio Utilizzo"
    ).split():
        assert name in text
    assert "Dodge" not in text and "Utilize" not in text


def test_area_of_effect_links_each_shape_to_its_rule(client, imported):
    html = _page(client, "area-of-effect", "it")

    for shape, slug in (("Cono", "cone"), ("Sfera", "sphere"), ("Emanazione", "emanation")):
        assert f'href="/world/rules/{slug}-area-of-effect/">{shape}</a>' in html


def test_condition_lists_the_same_fifteen_conditions_as_the_handbook(client, imported):
    text = _text(_page(client, "condition", "it"))

    assert "Accecato Affascinato Afferrato Assordato Avvelenato" in text
    assert "Privo di sensi Prono Spaventato Stordito Trattenuto" in text


def test_breaking_objects_translates_its_table_and_last_block_and_badges_them(client, imported):
    html = _page(client, "breaking-objects", "it")
    text = _text(html)

    assert _badged_headings(html) == ["Classe Armatura", "Nessun punteggio di caratteristica"]
    assert re.search(
        r"<caption>Classe Armatura degli oggetti\s*<span class=\"self-translated", html
    )
    for substance in ("Pietra", "Ferro, acciaio", "Adamantio"):
        assert substance in text
    for english in ("Object Armor Class", "Substance", "Stone", "No Ability Scores", "Adamantite"):
        assert english not in text
    # the intro no longer swallows the "Armor Class" sub-heading
    assert "Utilizzo. Classe Armatura." not in text


def test_grappling_and_long_rest_blocks_are_translated_and_badged(client, imported):
    grappling = _page(client, "grappling", "it")
    assert _badged_headings(grappling) == ["Una presa per ogni mano", "Sfuggire a una presa"]
    assert "A creature must have a hand free" not in grappling
    assert "CD di fuga" in grappling

    long_rest = _page(client, "long-rest", "it")
    assert _badged_headings(long_rest) == ["Interruzioni del riposo"]
    assert "Un riposo lungo viene interrotto dai seguenti eventi" in long_rest
    assert "Interrupting the Rest" not in long_rest


def test_the_english_pages_are_untouched(client, imported):
    text = _text(_page(client, "action", "en"))

    assert "On your turn, you can take one action" in text and "Dodge" in text
    assert "Classe Armatura" not in _text(_page(client, "breaking-objects", "en"))

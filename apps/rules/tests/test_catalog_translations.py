import pytest
from django.core.management import call_command
from django.utils import translation

from apps.frontend.entries_render import render_entries
from apps.rules.models import (
    Background,
    Class,
    Equipment,
    Feat,
    Feature,
    Rule,
    Species,
    Spell,
    Subclass,
)


@pytest.fixture
def catalogs(db):
    call_command("import_rules_data")  # also loads db/it/*.json (see sync_catalogs)


def test_translated_rows_read_in_italian_and_the_rest_fall_back(catalogs):
    with translation.override("it"):
        assert Feat.objects.get(pk="alert").name == "Allerta"
        assert Spell.objects.get(pk="fireball").name == "Palla di fuoco"
        assert Rule.objects.get(pk="advantage").name == "Vantaggio"
        # a feat outside the SRD has no Italian text: it keeps showing English, it isn't removed
        assert Feat.objects.get(pk="actor").name == "Actor"
        assert Feat.objects.get(pk="actor").entries == Feat.objects.get(pk="actor").entries_en

    with translation.override("en"):
        assert Spell.objects.get(pk="fireball").name == "Fireball"


def test_translations_do_not_remove_or_change_english_rows(catalogs):
    assert Spell.objects.count() == 391
    assert Feat.objects.count() == 77
    assert Rule.objects.count() == 114
    assert not Spell.objects.filter(name_en__isnull=True).exists()


def test_italian_text_keeps_the_english_tags(catalogs):
    fireball = Spell.objects.get(pk="fireball")

    # `{@damage 8d6}` wraps the dice in the Italian text too, and the higher-level block is
    # translated separately from the main description
    assert "{@damage 8d6}" in str(fireball.entries_it)
    assert (
        fireball.entries_higher_level_it[0]["name"]
        == "Utilizzo di uno slot incantesimo di livello superiore"
    )


def test_reference_tags_still_link_when_the_display_text_is_italian(catalogs):
    with translation.override("it"):
        html = render_entries(["Tira per l'{@variantrule Initiative|XPHB|iniziativa}."])

    assert 'href="/world/rules/initiative/"' in html
    assert ">iniziativa</a>" in html


def test_every_catalog_file_merges_onto_the_english_rows(catalogs):
    # `import_rules_data` already raised if any tree was misaligned; also spot-check coverage
    assert Spell.objects.filter(name_it__isnull=False).count() == 335
    assert Feat.objects.filter(name_it__isnull=False).count() == 17
    assert Rule.objects.filter(name_it__isnull=False).count() == 101


def test_classes_species_backgrounds_and_equipment_read_in_italian(catalogs):
    with translation.override("it"):
        assert Class.objects.get(pk="barbarian").name == "Barbaro"
        assert Class.objects.get(pk="barbarian").subclass_title == "Sottoclasse del barbaro"
        assert Species.objects.get(pk="dragonborn").name == "Dragonide"
        assert Species.objects.get(pk="dragonborn").short_description.startswith("Fieri")
        assert Background.objects.get(pk="acolyte").name == "Accolito"
        assert Equipment.objects.get(pk="dagger").name == "Pugnale"
        assert Subclass.objects.get(name_en="Path of the Berserker").name == "Cammino del berserker"
        rage = Feature.objects.get(class_level__klass_id="barbarian", name_en="Rage")
        assert rage.name == "Ira"

    with translation.override("en"):
        assert Class.objects.get(pk="barbarian").name == "Barbarian"
        assert Equipment.objects.get(pk="dagger").name == "Dagger"


def test_rows_without_italian_source_stay_in_english(catalogs):
    with translation.override("it"):
        # Aasimar/Grung are not in the SRD (only their one-line blurb is Italian); non-SRD
        # backgrounds and subclasses have no Italian at all
        assert Species.objects.get(pk="aasimar").name == "Aasimar"
        assert Background.objects.get(pk="artisan").name == "Artisan"
        assert (
            Subclass.objects.get(name_en="Path of the Wild Heart").name == "Path of the Wild Heart"
        )
    assert Species.objects.count() == 11
    assert Background.objects.count() == 16
    assert Equipment.objects.count() == 217
    assert Feature.objects.count() == 707


def test_feature_translations_survive_a_reimport(catalogs):
    # Feature/Subclass ids are auto-incrementing, so files are keyed by class/level/name instead
    call_command("import_rules_data")

    with translation.override("it"):
        assert Feature.objects.get(class_level__klass_id="barbarian", name_en="Rage").name == "Ira"

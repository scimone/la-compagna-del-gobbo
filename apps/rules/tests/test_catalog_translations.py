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
        # a feat outside the SRD is hand-translated now (see `self_translated_fields`), not English
        assert Feat.objects.get(pk="actor").name == "Attore"
        assert set(Feat.objects.get(pk="actor").self_translated_fields) == {"name", "entries"}
        assert Feat.objects.get(pk="alert").self_translated_fields == []

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
    assert Spell.objects.filter(name_it__isnull=False).count() == 391
    assert Feat.objects.filter(name_it__isnull=False).count() == 77
    assert Rule.objects.filter(name_it__isnull=False).count() == 114


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


def test_rows_without_an_official_source_are_hand_translated_and_flagged(catalogs):
    # Aasimar/Grung, every non-SRD background, and every non-SRD subclass had no official
    # Italian source (the SRD PDF) - they're hand-translated for this project now instead of
    # staying English, and `self_translated_fields` says exactly which of their own fields.
    # Lore (PHB-only flavor text, never covered by the SRD) is hand-translated for every
    # Species/Background/Class, including SRD ones - so an otherwise-official row like "elf"
    # still lists "lore" (and nothing else) once any part of it is hand-translated.
    with translation.override("it"):
        assert Species.objects.get(pk="aasimar").name == "Aasimar"  # a proper noun, unchanged
        assert set(Species.objects.get(pk="aasimar").self_translated_fields) == {
            "name",
            "lore",
            "entries",
        }
        assert Species.objects.get(pk="elf").self_translated_fields == ["lore"]
        assert Background.objects.get(pk="artisan").name == "Artigiano"
        assert "name" in Background.objects.get(pk="artisan").self_translated_fields
        wild_heart = Subclass.objects.get(name_en="Path of the Wild Heart")
        assert wild_heart.name != "Path of the Wild Heart"
        assert set(wild_heart.self_translated_fields) == {"name", "description"}
        # a row with no hand-translated field at all is never flagged
        assert Equipment.objects.get(pk="dagger").self_translated_fields == []
        assert Rule.objects.get(pk="advantage").self_translated_fields == []
    assert Species.objects.count() == 11
    assert Background.objects.count() == 16
    assert Equipment.objects.count() == 217
    assert Feature.objects.count() == 695


def test_a_classfeature_subheading_is_nested_not_a_sibling_feature(catalogs):
    # Monk's Martial Arts embeds Bonus Unarmed Strike/Martial Arts Die/Dexterous Attacks via
    # `refClassFeature` pointers to `classFeature` rows marked with a `header` (5etools' own
    # nesting-depth marker - see `_inline_header_class_features()`'s docstring) - the book itself
    # presents them as sub-entries of Martial Arts, not as three more level-1 Monk features
    # alongside it and Unarmored Defense.
    monk = Class.objects.get(id="monk")
    level_1_names = set(
        Feature.objects.filter(class_level__klass=monk, class_level__level=1).values_list(
            "name_en", flat=True
        )
    )
    assert level_1_names == {"Martial Arts", "Unarmored Defense"}

    martial_arts = Feature.objects.get(
        class_level__klass=monk, class_level__level=1, name_en="Martial Arts"
    )
    with translation.override("it"):
        html = render_entries(martial_arts.entries)
    # `'` renders HTML-escaped (`&#x27;`) inside `_render_text()` - checked without it.
    assert "<h3>Colpo senz" in html and "armi bonus</h3>" in html
    assert "<h3>Dado di Arti marziali</h3>" in html
    assert "<h3>Attacchi destri</h3>" in html


def test_feature_rows_only_used_as_a_queryable_index_are_left_untranslated(catalogs):
    # Species/Feat-linked `Feature` rows duplicate text already translated on the parent's own
    # `entries` field (see `Feature`'s docstring) and are never rendered on any page directly -
    # translating them a second time would be pure invisible busywork, so they're the one
    # deliberate gap left in an otherwise fully-covered set of catalogs.
    assert not Feature.objects.filter(class_level__isnull=False, name_it__isnull=True).exists()
    assert not Feature.objects.filter(subclass_level__isnull=False, name_it__isnull=True).exists()
    assert Feature.objects.filter(species__isnull=False, name_it__isnull=True).exists()
    assert Feature.objects.filter(feat__isnull=False, name_it__isnull=True).exists()


def test_feature_translations_survive_a_reimport(catalogs):
    # Feature/Subclass ids are auto-incrementing, so files are keyed by class/level/name instead
    call_command("import_rules_data")

    with translation.override("it"):
        assert Feature.objects.get(class_level__klass_id="barbarian", name_en="Rage").name == "Ira"


def test_paragraph_level_matches_fill_features_the_exact_matcher_rejected(catalogs):
    # Spellcasting/Fighting Style/Paladin's Smite differ from the book by a leaf or two
    # (English splits and nests features differently), so they come from the paragraph-level pass
    with translation.override("it"):
        for name in ("Spellcasting", "Fighting Style", "Paladin's Smite", "Channel Divinity"):
            feature = Feature.objects.get(class_level__klass_id="paladin", name_en=name)
            assert feature.entries != feature.entries_en, name

        # repeated Ability Score Improvement rows reuse the level-4 text
        asi = Feature.objects.get(
            class_level__klass_id="paladin",
            class_level__level=8,
            name_en="Ability Score Improvement",
        )
        assert asi.name == "Aumento dei punteggi di caratteristica"


def test_a_spell_option_is_not_matched_to_a_different_option(catalogs):
    # Symbol lists several effects that all say "1 minute"; the paragraph matcher must not pair
    # an English "Constitution ... Incapacitated" option with the Italian "Wisdom ... frightened"
    symbol = Spell.objects.get(pk="symbol")
    for english, italian in zip(symbol.entries_en, symbol.entries_it or [], strict=False):
        if isinstance(english, str) and isinstance(italian, str) and "Incapacitated" in english:
            assert "spaventat" not in italian.lower() or "Constitution" not in english

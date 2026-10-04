import pytest

from apps.builder.services import feature_resources, land
from apps.builder.services.feature_resources import FEATURE_RESOURCES
from apps.characters.services import play
from apps.rules.models import Feat, Feature, Species, Subclass

from .conftest import build_character
from .test_progression import autofill, finished, level_up

pytestmark = pytest.mark.usefixtures("imported_rules")


def test_every_spec_row_names_a_feature_of_the_imported_data(db):
    for row in FEATURE_RESOURCES:
        if row.owner == "species":
            qs = Feature.objects.filter(species_id=row.key)
            assert Species.objects.filter(pk=row.key).exists(), row
        elif row.owner == "feat":
            qs = Feature.objects.filter(feat_id=row.key)
            assert Feat.objects.filter(pk=row.key).exists(), row
        elif row.owner == "class":
            qs = Feature.objects.filter(class_level__klass_id=row.key)
        else:
            qs = Feature.objects.filter(subclass_level__subclass__name_en=row.key)
        names = qs.values_list("name_en", flat=True)
        assert any(feature_resources._name_matches(n, row.feature) for n in names), row


def test_a_species_trait_becomes_a_resource_that_a_long_rest_restores(owner):
    character = build_character(owner, "fighter", "soldier", "dragonborn")
    breath = character.resources.get(name="Breath Weapon")
    assert breath.max_uses == 2 and breath.reset_on == "long_rest"
    breath.current_uses = 0
    breath.save()
    play.long_rest(character)
    breath.refresh_from_db()
    assert breath.current_uses == 2


def test_circle_of_the_land_asks_for_a_new_land_after_a_long_rest(owner):
    character = finished(owner, "druid")
    level_up(character, "druid")
    land_subclass = Subclass.objects.get(klass_id="druid", name_en="Circle of the Land")
    values = autofill(
        character,
        "druid",
        prefer={"lu.subclass": [str(land_subclass.pk)], "lu.land": ["Polar Land"]},
    )
    from apps.builder.services import progression

    progression.commit(character, "druid", values)
    assert land.land_options(character) is None  # nothing is open before a rest

    play.long_rest(character)
    character.refresh_from_db()
    assert land.land_options(character)["current"] == "Polar Land"

    land.change_land(character, "Arid Land")
    names = set(character.features.values_list("feature__name_en", flat=True))
    assert "Circle of the Land Spells (Arid Land)" in names
    assert "Circle of the Land Spells (Polar Land)" not in names
    spells = set(
        character.spells.filter(source=f"subclass:{land_subclass.pk}").values_list(
            "spell_id", flat=True
        )
    )
    assert "burning-hands" in spells and "fog-cloud" not in spells
    assert land.land_options(character) is None
    with pytest.raises(ValueError):
        land.change_land(character, "Arid Land")

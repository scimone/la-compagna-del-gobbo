"""The Use button of every feature that has a counter."""

import pytest
from django.contrib.auth import get_user_model

from apps.builder.progression_spec import LEVEL_RESOURCES
from apps.builder.services import creation, wild_shape
from apps.builder.services.feature_resources import FEATURE_RESOURCES
from apps.builder.tests.conftest import build_character
from apps.characters.models import CharacterResource
from apps.frontend.character_sheet import _resource_name
from apps.rules.models import Feature

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def signed_in(client, alice):
    client.force_login(alice)
    return client


def finished(owner, class_id, background="acolyte", species="human"):
    character = build_character(owner, class_id, background, species, "Test")
    creation.finalize(character)
    character.refresh_from_db()
    return character


def act(client, character, **data):
    return client.post(f"/characters/{character.pk}/act/", data)


def features_panel(client, character):
    html = client.get(f"/characters/{character.pk}/").content.decode()
    return html.split('data-panel="features"')[1].split('data-panel="spellbook"')[0]


def test_every_counter_has_a_feature_card_to_use_it_from(db):
    names = {r.name for rows in LEVEL_RESOURCES.values() for r in rows}
    names |= {r.feature for r in FEATURE_RESOURCES}
    cards = {_resource_name(n) for n in Feature.objects.values_list("name_en", flat=True)}
    # Wild Shape is used from one of its forms (the "Wild Shape: <beast>" cards).
    assert sorted(n for n in names - {"Wild Shape"} if n not in cards) == []


def test_a_feature_card_spends_its_counter_with_use(signed_in, alice):
    fighter = finished(alice, "fighter", "soldier")
    wind = fighter.resources.get(name="Second Wind")
    html = features_panel(signed_in, fighter)
    assert f'data-resource="{wind.pk}"' in html and "Use 2/2" in html

    assert act(signed_in, fighter, action="resource_use", resource=wind.pk).status_code == 200
    assert "Use 1/2" in features_panel(signed_in, fighter)
    act(signed_in, fighter, action="resource_use", resource=wind.pk)
    assert act(signed_in, fighter, action="resource_use", resource=wind.pk).status_code == 400
    assert "disabled>Use 0/2" in features_panel(signed_in, fighter).replace("\n", "")

    act(signed_in, fighter, action="long_rest")
    assert "Use 2/2" in features_panel(signed_in, fighter)


def test_a_species_trait_with_a_counter_can_be_used_too(signed_in, alice):
    dragonborn = finished(alice, "fighter", "soldier", "dragonborn")
    breath = dragonborn.resources.get(name="Breath Weapon")
    assert f'data-resource="{breath.pk}"' in features_panel(signed_in, dragonborn)


def test_a_pool_asks_how_many_points_to_spend(signed_in, alice):
    paladin = finished(alice, "paladin", "soldier")
    pool = paladin.resources.get(name="Lay on Hands")
    html = features_panel(signed_in, paladin)
    assert f'data-resource="{pool.pk}"' in html and f'data-ask-amount="{pool.max_uses}"' in html
    assert (
        act(signed_in, paladin, action="resource_use", resource=pool.pk, amount="3").status_code
        == 200
    )
    assert paladin.resources.get(name="Lay on Hands").current_uses == pool.max_uses - 3
    too_many = act(signed_in, paladin, action="resource_use", resource=pool.pk, amount="99")
    assert too_many.status_code == 400


def test_only_the_owner_sees_use_and_wild_shape_is_not_a_plain_counter(signed_in, alice):
    druid = finished(alice, "druid")
    druid.classes.update(level=2)
    wild_shape.add_forms(druid, ["wolf", "rat", "spider", "riding-horse"])
    row = CharacterResource.objects.create(
        character=druid, name="Wild Shape", max_uses=2, current_uses=2, reset_on="other"
    )
    assert act(signed_in, druid, action="resource_use", resource=row.pk).status_code == 400
    html = features_panel(signed_in, druid)
    assert 'data-form="wolf"' in html and f'data-resource="{row.pk}"' not in html

    # In a form already, that form's own card has no Use button (the others still do).
    act(signed_in, druid, action="wild_shape_use", form="wolf")
    html = features_panel(signed_in, druid)
    assert 'data-form="wolf"' not in html and 'data-form="rat"' in html

    other = get_user_model().objects.create_user("bob")
    signed_in.force_login(other)
    assert 'data-act="wild_shape_use"' not in features_panel(signed_in, druid)

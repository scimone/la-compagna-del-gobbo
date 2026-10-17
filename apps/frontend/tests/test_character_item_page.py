"""An item's own page (`character_item()`): what an inventory row and a row of the "add an item"
list open - the description, plus the editor's tools as plain forms."""

import pytest
from django.contrib.auth import get_user_model

from apps.builder.services import creation
from apps.builder.tests.conftest import build_character
from apps.characters.models import CharacterCustomItem, CharacterInventoryItem
from apps.characters.services import play

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def bob(db):
    return get_user_model().objects.create_user("bob")


@pytest.fixture
def signed_in(client, alice):
    client.force_login(alice)
    return client


@pytest.fixture
def cleric(alice):
    character = build_character(alice, "cleric", "acolyte", "human", "Test")
    creation.finalize(character)
    character.refresh_from_db()
    return character


def test_an_inventory_row_opens_the_items_page_where_it_can_be_edited_sold_and_removed(
    signed_in, cleric
):
    mace = cleric.inventory_items.get(equipment_id="mace")

    page = signed_in.get(f"/characters/{cleric.pk}/inventory/{mace.pk}/")

    assert page.status_code == 200
    text = page.content.decode()
    assert "Mace" in text and "bludgeoning" in text  # the catalog's own facts and description
    for action in ("item_qty", "equip", "item_sell", "item_remove"):
        assert f'value="{action}"' in text
    assert "Equipment sells for half its cost." in text
    assert f'href="/characters/{cleric.pk}/?tab=inventory"' in text  # back to the inventory


def test_the_items_page_forms_change_the_item_and_removing_it_goes_back_to_the_inventory(
    signed_in, cleric
):
    torches = CharacterInventoryItem.objects.create(
        character=cleric, equipment_id="torch", quantity=10
    )
    url = f"/characters/{cleric.pk}/inventory/{torches.pk}/"

    more = signed_in.post(url, {"action": "item_qty", "delta": "1"})
    assert more.status_code == 302 and more["Location"] == url
    torches.refresh_from_db()
    assert torches.quantity == 11
    signed_in.post(url, {"action": "item_qty", "value": "3"})
    torches.refresh_from_db()
    assert torches.quantity == 3

    gone = signed_in.post(url, {"action": "item_remove"})

    assert gone.status_code == 302 and gone["Location"] == f"/characters/{cleric.pk}/?tab=inventory"
    assert not CharacterInventoryItem.objects.filter(pk=torches.pk).exists()
    assert signed_in.get(url).status_code == 404


def test_selling_from_the_items_page_pays_out_and_a_sold_out_stack_goes_back(signed_in, cleric):
    torches = CharacterInventoryItem.objects.create(
        character=cleric, equipment_id="torch", quantity=10
    )
    url = f"/characters/{cleric.pk}/inventory/{torches.pk}/"
    before = play.purse_copper(cleric)

    sold = signed_in.post(url, {"action": "item_sell", "quantity": "10"})

    assert sold["Location"] == f"/characters/{cleric.pk}/?tab=inventory"
    assert play.purse_copper(cleric) == before + 5  # ten torches at half of 1 cp each, in total


def test_the_items_page_only_takes_the_actions_of_its_own_kind_and_only_from_the_owner(
    signed_in, client, cleric, bob
):
    mace = cleric.inventory_items.get(equipment_id="mace")
    url = f"/characters/{cleric.pk}/inventory/{mace.pk}/"

    assert signed_in.post(url, {"action": "item_buy"}).status_code == 400  # a catalog action
    assert signed_in.post(url, {"action": "nonsense"}).status_code == 400
    client.force_login(bob)
    viewer = client.get(url)
    assert viewer.status_code == 200 and 'value="item_remove"' not in viewer.content.decode()
    assert client.post(url, {"action": "item_remove"}).status_code == 403
    assert cleric.inventory_items.filter(pk=mace.pk).exists()


def test_an_item_of_another_character_is_not_found_under_this_ones_url(signed_in, alice, cleric):
    other = build_character(alice, "fighter", "soldier", "human", "Other")
    creation.finalize(other)
    theirs = other.inventory_items.first()

    assert signed_in.get(f"/characters/{cleric.pk}/inventory/{theirs.pk}/").status_code == 404


def test_a_custom_items_page_shows_what_the_player_wrote_and_its_tools(signed_in, cleric):
    item = CharacterCustomItem.objects.create(
        character=cleric, name="Odd Locket", section="misc", quantity=2, description="Warm."
    )

    page = signed_in.get(f"/characters/{cleric.pk}/inventory/custom/{item.pk}/")

    text = page.content.decode()
    assert page.status_code == 200 and "Odd Locket" in text and "Warm." in text
    assert 'value="item_qty"' in text and 'value="item_remove"' in text
    signed_in.post(page.request["PATH_INFO"], {"action": "item_remove"})
    assert not CharacterCustomItem.objects.filter(pk=item.pk).exists()


def test_a_catalog_items_page_offers_add_and_buy_and_buying_pays(signed_in, cleric):
    play.set_coin(cleric, "gold", 100)
    url = f"/characters/{cleric.pk}/catalog/mace/"

    text = signed_in.get(url).content.decode()

    assert 'value="item_add"' in text and 'value="item_buy"' in text
    assert f'href="/characters/{cleric.pk}/?tab=inventory&amp;overlay=item"' in text  # back
    before = play.purse_copper(cleric)
    bought = signed_in.post(url, {"action": "item_buy"})
    assert bought.status_code == 302 and bought["Location"] == url
    assert play.purse_copper(cleric) == before - 500
    assert "Bought Mace" in signed_in.get(url).content.decode()  # the note about it
    added = signed_in.post(url, {"action": "item_add"})
    assert added.status_code == 302
    assert play.purse_copper(cleric) == before - 500  # adding is free


def test_a_catalog_item_the_purse_cannot_pay_is_not_offered_for_buying(signed_in, cleric):
    for coin in ("copper", "silver", "electrum", "gold", "platinum"):
        play.set_coin(cleric, coin, 0)

    text = signed_in.get(f"/characters/{cleric.pk}/catalog/mace/").content.decode()

    assert 'value="item_add"' in text and 'value="item_buy"' not in text
    refused = signed_in.post(f"/characters/{cleric.pk}/catalog/mace/", {"action": "item_buy"})
    assert refused.status_code == 302  # back to the page, with a note - nothing charged or added
    assert not cleric.inventory_items.filter(equipment_id="mace", quantity__gt=1).exists()


def test_the_add_item_list_rows_link_to_the_items_page_without_a_toggle(signed_in, cleric):
    html = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()

    assert f'href="/characters/{cleric.pk}/catalog/mace/"' in html
    assert 'class="chev"' not in html and "data-describe=" not in html


def test_a_custom_item_can_be_edited_and_given_stats_to_be_equipped(signed_in, cleric):
    item = play.add_custom_item(cleric, name="Old blade", section="weapons")
    url = f"/characters/{cleric.pk}/inventory/custom/{item.pk}/"

    page = signed_in.get(url).content.decode()
    assert "?edit=1" in page and 'name="damage_dice"' not in page  # the form is a page of its own
    page = signed_in.get(f"{url}?edit=1").content.decode()
    assert 'value="custom_edit"' in page and 'name="damage_dice"' in page

    signed_in.post(
        url,
        {
            "action": "custom_edit",
            "name": "Moon blade",
            "section": "weapons",
            "weapon_category": "martial",
            "damage_dice": "1d8",
            "damage_type": "slashing",
            "versatile_damage_dice": "1d10",
            "cost": "50",
            "weight": "3",
        },
    )
    item.refresh_from_db()
    assert item.name == "Moon blade" and item.versatile_damage_dice == "1d10"
    assert item.value == 5000

    signed_in.post(url, {"action": "equip", "value": "1"})
    item.refresh_from_db()
    assert item.equipped
    page = signed_in.get(url).content.decode()
    assert "1d8 slashing (1d10 two-handed)" in page


def test_adding_many_through_the_sheet_endpoint(signed_in, cleric):
    act = f"/characters/{cleric.pk}/act/"
    signed_in.post(act, {"action": "item_add", "equipment": "torch", "quantity": "10"})
    assert (
        sum(cleric.inventory_items.filter(equipment_id="torch").values_list("quantity", flat=True))
        >= 10
    )


def test_editing_an_item_shows_only_the_fields_of_its_category(signed_in, cleric):
    armor = play.add_custom_item(cleric, name="Robe", section="armor", armor_kind="light", ac=11)
    page = signed_in.get(
        f"/characters/{cleric.pk}/inventory/custom/{armor.pk}/?edit=1"
    ).content.decode()
    assert 'name="armor_kind"' in page and 'name="ac"' in page
    assert 'name="damage_dice"' not in page and 'name="weapon_category"' not in page
    assert 'name="effects"' in page


def test_a_ranged_custom_weapon_is_given_a_range_and_a_plain_item_effects(signed_in, cleric):
    bow = play.add_custom_item(
        cleric, name="Bow", section="weapons", damage_dice="1d8", ranged=True
    )
    url = f"/characters/{cleric.pk}/inventory/custom/{bow.pk}/"
    signed_in.post(
        url,
        {
            "action": "custom_edit",
            "name": "Bow",
            "damage_dice": "1d8",
            "ranged": "1",
            "range_normal": "24",
            "range_long": "96",
        },
    )
    bow.refresh_from_db()
    assert bow.range == "80/320"
    assert "24/96 m" in signed_in.get(url).content.decode()  # typed and shown in metres
    ring = play.add_custom_item(cleric, name="Ring")
    ring_url = f"/characters/{cleric.pk}/inventory/custom/{ring.pk}/"
    signed_in.post(
        ring_url,
        {
            "action": "custom_edit",
            "name": "Ring",
            "effects": '[{"target": "ac", "value": 2}]',
        },
    )
    page = signed_in.get(ring_url).content.decode()
    assert "+2 Armor Class" in page and 'value="equip"' in page


def test_custom_features_are_added_listed_edited_and_removed(signed_in, cleric):
    act = f"/characters/{cleric.pk}/act/"
    response = signed_in.post(
        act,
        {
            "action": "custom_feature_add",
            "name": "Fey touched",
            "description": "Seen by the Fey.",
            "effects": '[{"target": "prof_skill:persuasion", "value": 1}]',
        },
    )
    assert response.json()["ok"]
    feature = cleric.custom_features.get()
    sheet = signed_in.get(f"/characters/{cleric.pk}/?tab=features").content.decode()
    assert "Fey touched" in sheet
    url = f"/characters/{cleric.pk}/features/custom/{feature.pk}/"
    page = signed_in.get(url).content.decode()
    assert "Seen by the Fey." in page and "Proficiency: Persuasion" in page
    assert 'name="effects"' in signed_in.get(f"{url}?edit=1").content.decode()
    signed_in.post(url, {"action": "custom_feature_edit", "name": "Fey kissed"})
    feature.refresh_from_db()
    assert feature.name == "Fey kissed" and feature.effects == []
    signed_in.post(url, {"action": "custom_feature_remove"})
    assert not cleric.custom_features.exists()

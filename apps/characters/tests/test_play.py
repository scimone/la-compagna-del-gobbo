"""Play-state changes (`characters.services.play`): what the character sheet lets the owner tick."""

import pytest

from apps.characters.models import (
    Character,
    CharacterClass,
    CharacterInventoryItem,
    CharacterSpell,
)
from apps.characters.services import play
from apps.rules.models import Class, Equipment, Spell

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def hero(db):
    return Character.objects.create(name="Hero", max_hit_points=20, current_hit_points=20)


def give(character, equipment_id, *, equipped=False):
    return CharacterInventoryItem.objects.create(
        character=character, equipment=Equipment.objects.get(pk=equipment_id), equipped=equipped
    )


# --- hit points --------------------------------------------------------------------------------


def test_damage_is_taken_from_temporary_hit_points_first(hero):
    hero.temporary_hit_points = 5

    play.adjust_hit_points(hero, -8)

    hero.refresh_from_db()
    assert (hero.temporary_hit_points, hero.current_hit_points) == (0, 17)


def test_healing_stops_at_the_maximum_and_damage_at_zero(hero):
    play.adjust_hit_points(hero, 50)
    assert hero.current_hit_points == 20

    play.adjust_hit_points(hero, -50)
    assert hero.current_hit_points == 0


def test_regaining_hit_points_from_zero_clears_the_death_saves(hero):
    hero.current_hit_points, hero.death_save_successes, hero.death_save_failures = 0, 2, 1
    hero.save()

    play.adjust_hit_points(hero, 1)

    hero.refresh_from_db()
    assert (hero.current_hit_points, hero.death_save_successes, hero.death_save_failures) == (
        1,
        0,
        0,
    )


def test_typing_a_hit_point_value_is_clamped_and_skips_temporary_hit_points(hero):
    hero.temporary_hit_points = 4
    play.set_hit_points(hero, 99)
    assert (hero.current_hit_points, hero.temporary_hit_points) == (20, 4)

    play.set_hit_points(hero, -3)
    assert hero.current_hit_points == 0


def test_death_save_boxes_tick_up_to_the_clicked_one_and_clear_when_clicked_again(hero):
    play.toggle_death_save(hero, "successes", 2)
    assert hero.death_save_successes == 2

    play.toggle_death_save(hero, "successes", 2)
    assert hero.death_save_successes == 1

    play.toggle_death_save(hero, "failures", 3)
    assert hero.death_save_failures == 3


def test_death_saves_reject_an_unknown_kind(hero):
    with pytest.raises(ValueError):
        play.toggle_death_save(hero, "luck", 1)


# --- hit dice ----------------------------------------------------------------------------------


def test_hit_dice_of_one_size_are_spread_over_the_classes_that_use_them(hero):
    fighter = CharacterClass.objects.create(
        character=hero, klass=Class.objects.get(pk="fighter"), level=3
    )
    paladin = CharacterClass.objects.create(
        character=hero, klass=Class.objects.get(pk="paladin"), level=2
    )

    play.set_hit_dice_spent(hero, "d10", 4)

    fighter.refresh_from_db()
    paladin.refresh_from_db()
    # Classes fill in order (highest level first): the fighter's 3 dice, then 1 of the paladin's.
    assert (fighter.hit_dice_spent, paladin.hit_dice_spent) == (3, 1)

    play.set_hit_dice_spent(hero, "d10", 99)
    fighter.refresh_from_db()
    paladin.refresh_from_db()
    assert fighter.hit_dice_spent + paladin.hit_dice_spent == 5  # never more than the pool

    play.set_hit_dice_spent(hero, "d10", -2)
    fighter.refresh_from_db()
    paladin.refresh_from_db()
    assert fighter.hit_dice_spent + paladin.hit_dice_spent == 0


def test_spending_a_hit_die_the_character_does_not_have_is_refused(hero):
    CharacterClass.objects.create(character=hero, klass=Class.objects.get(pk="wizard"), level=1)

    with pytest.raises(ValueError):
        play.set_hit_dice_spent(hero, "d12", 1)


# --- spell slots -------------------------------------------------------------------------------


def test_spent_slots_are_clamped_to_what_the_character_has(hero):
    play.set_slots_spent(hero, "1", 9, maximum=4)
    assert hero.spell_slots_spent == {"1": 4}

    play.set_slots_spent(hero, "pact", 1, maximum=2)
    play.set_slots_spent(hero, "1", -1, maximum=4)
    hero.refresh_from_db()
    assert hero.spell_slots_spent == {"1": 0, "pact": 1}


def test_an_unknown_slot_key_is_refused(hero):
    with pytest.raises(ValueError):
        play.set_slots_spent(hero, "bonus", 1, maximum=1)


# --- coins, gear, text -------------------------------------------------------------------------


def test_coins_are_created_on_first_use_and_never_negative(hero):
    play.set_coin(hero, "gold", 15)
    play.set_coin(hero, "copper", -4)

    hero.refresh_from_db()
    assert (hero.currency.gold, hero.currency.copper) == (15, 0)
    with pytest.raises(ValueError):
        play.set_coin(hero, "doubloons", 1)


def test_wearing_body_armor_takes_off_the_armor_already_worn_but_not_the_shield(hero):
    chain = give(hero, "chain-mail", equipped=True)
    shield = give(hero, "shield", equipped=True)
    leather = give(hero, "leather-armor")

    play.set_equipped(hero, leather.pk, True)

    for row in (chain, shield, leather):
        row.refresh_from_db()
    assert (chain.equipped, shield.equipped, leather.equipped) == (False, True, True)


def test_only_one_shield_is_worn_and_gear_that_cannot_be_worn_is_refused(hero):
    first = give(hero, "shield", equipped=True)
    second = give(hero, "shield")
    rope = give(hero, "rope")

    play.set_equipped(hero, second.pk, True)

    first.refresh_from_db()
    assert first.equipped is False
    with pytest.raises(ValueError):
        play.set_equipped(hero, rope.pk, True)


def test_names_and_free_text(hero):
    play.rename(hero, "  Aragorn  ")
    assert hero.name == "Aragorn"
    with pytest.raises(ValueError):
        play.rename(hero, "   ")

    play.set_text(hero, "backstory", "Ranger of the North.")
    assert Character.objects.get(pk=hero.pk).backstory == "Ranger of the North."
    with pytest.raises(ValueError):
        play.set_text(hero, "max_hit_points", "1000")


# --- items: add, count, remove, sell -----------------------------------------------------------


def test_adding_catalog_gear_stacks_onto_the_loose_stack_but_not_onto_a_packs_contents(hero):
    pack = give(hero, "explorers-pack")
    inside = CharacterInventoryItem.objects.create(
        character=hero, equipment=Equipment.objects.get(pk="rope"), parent=pack
    )

    first = play.add_item(hero, "rope")
    second = play.add_item(hero, "rope", 2)

    assert first.pk == second.pk != inside.pk  # its own stack, not the pack's rope
    second.refresh_from_db()
    assert second.quantity == 3
    assert hero.inventory_items.filter(equipment_id="rope").count() == 2
    with pytest.raises(Equipment.DoesNotExist):
        play.add_item(hero, "no-such-item")


def test_buying_pays_for_the_item_and_adds_it_stacking_like_add_item(hero):
    play.set_coin(hero, "gold", 20)

    item, price = play.buy_item(hero, "rope")  # 1 gp
    again, _price = play.buy_item(hero, "rope")

    assert price == 100 and item.pk == again.pk
    again.refresh_from_db()
    assert again.quantity == 2
    hero.refresh_from_db()
    assert hero.currency.gold == 18


def test_buying_spends_the_purse_breaking_only_the_coin_it_needs_to(hero):
    play.set_coin(hero, "platinum", 2)  # 2000 cp, nothing else

    play.buy_item(hero, "rope")  # 1 gp = 100 cp, out of 2000

    hero.refresh_from_db()
    # 1900 cp left: one platinum piece kept whole, the rest re-minted as gold (never electrum -
    # the purse never had any) since a purchase only ever breaks what it must.
    assert (hero.currency.platinum, hero.currency.electrum, hero.currency.gold) == (1, 0, 9)


def test_buying_without_enough_money_or_a_price_is_refused_and_nothing_changes(hero):
    play.set_coin(hero, "gold", 0)

    with pytest.raises(ValueError):
        play.buy_item(hero, "rope")
    assert not hero.inventory_items.exists()

    play.set_coin(hero, "gold", 99)
    Equipment.objects.filter(pk="rope").update(value=0)
    with pytest.raises(ValueError):
        play.buy_item(hero, "rope")
    assert not hero.inventory_items.exists()
    hero.refresh_from_db()
    assert hero.currency.gold == 99  # untouched by the refused purchase


def test_custom_items_are_validated_and_stored_in_copper(hero):
    item = play.add_custom_item(
        hero,
        name="  Lucky coin ",
        section="misc",
        type_label="  Trinket ",
        value=250,
        weight=0.1,
        valuable=True,
    )

    assert (item.name, item.value, item.valuable, item.quantity) == ("Lucky coin", 250, True, 1)
    assert item.type_label == "Trinket"
    untyped = play.add_custom_item(hero, name="Rock")
    assert untyped.type_label == ""
    with pytest.raises(ValueError):
        play.add_custom_item(hero, name=" ")
    with pytest.raises(ValueError):
        play.add_custom_item(hero, name="x", section="vehicles")
    with pytest.raises(ValueError):
        play.add_custom_item(hero, name="x", value=-1)


def test_quantity_never_drops_below_one(hero):
    stack = give(hero, "rope")

    play.set_item_quantity(hero, "catalog", stack.pk, 7)
    play.adjust_item_quantity(hero, "catalog", stack.pk, -20)

    stack.refresh_from_db()
    assert stack.quantity == 1
    with pytest.raises(ValueError):
        play.set_item_quantity(hero, "vehicle", stack.pk, 2)


def test_removing_the_last_item_of_a_pack_removes_the_empty_pack_too(hero):
    pack = give(hero, "explorers-pack")
    rope = CharacterInventoryItem.objects.create(
        character=hero, equipment=Equipment.objects.get(pk="rope"), parent=pack
    )
    torch = CharacterInventoryItem.objects.create(
        character=hero, equipment=Equipment.objects.get(pk="torch"), parent=pack
    )

    play.remove_item(hero, "catalog", rope.pk)
    assert CharacterInventoryItem.objects.filter(pk=pack.pk).exists()

    play.remove_item(hero, "catalog", torch.pk)
    assert not CharacterInventoryItem.objects.filter(pk=pack.pk).exists()


def test_equipment_sells_for_half_its_cost_and_valuables_for_all_of_it():
    assert play.sale_price(1000, 1, full_value=False) == 500
    assert play.sale_price(1000, 3, full_value=False) == 1500
    assert play.sale_price(1000, 3, full_value=True) == 3000
    assert play.sale_price(1, 1, full_value=False) == 0  # half a copper piece is nothing
    assert play.sale_price(None, 4, full_value=True) == 0


def test_selling_pays_coins_and_uses_up_the_items(hero):
    play.set_coin(hero, "gold", 10)
    shield = give(hero, "shield", equipped=True)  # costs 10 gp
    torches = give(hero, "torch")
    torches.quantity = 10  # 1 cp each
    torches.save()

    paid = play.sell_item(hero, "catalog", shield.pk)

    assert paid == 500  # 5 gp, half of the shield's 10 gp
    hero.refresh_from_db()
    assert hero.currency.gold == 15
    assert not CharacterInventoryItem.objects.filter(pk=shield.pk).exists()
    with pytest.raises(ValueError):  # ten torches at 1 cp each are worth 5 cp: one is worth nothing
        play.sell_item(hero, "catalog", torches.pk, 1)
    assert play.sell_item(hero, "catalog", torches.pk, 99) == 5  # more than there are: all of them
    hero.refresh_from_db()
    assert (hero.currency.gold, hero.currency.copper) == (15, 5)


def test_selling_part_of_a_stack_keeps_the_rest_and_a_valuable_sells_whole(hero):
    stack = give(hero, "rope")  # 1 gp
    stack.quantity = 4
    stack.save()
    gem = play.add_custom_item(hero, name="Ruby", value=5000, valuable=True, quantity=2)
    junk = play.add_custom_item(hero, name="Old boot", value=100)
    worthless = play.add_custom_item(hero, name="Pebble")

    assert play.sell_item(hero, "catalog", stack.pk, 2) == 100  # 2 x 1 gp, halved
    stack.refresh_from_db()
    assert stack.quantity == 2
    assert play.sell_item(hero, "custom", gem.pk, 1) == 5000  # a valuable keeps its full value
    assert play.sell_item(hero, "custom", junk.pk) == 50
    with pytest.raises(ValueError):
        play.sell_item(hero, "custom", worthless.pk)
    gem.refresh_from_db()
    assert gem.quantity == 1 and not hero.custom_items.filter(pk=junk.pk).exists()
    hero.refresh_from_db()
    assert (hero.currency.gold, hero.currency.silver) == (51, 5)  # 100 + 5000 + 50 cp


def test_an_item_that_is_not_the_characters_cannot_be_touched(hero, db):
    other = Character.objects.create(name="Other")
    theirs = give(other, "rope")

    for action in (
        lambda: play.remove_item(hero, "catalog", theirs.pk),
        lambda: play.sell_item(hero, "catalog", theirs.pk),
        lambda: play.set_item_quantity(hero, "catalog", theirs.pk, 3),
    ):
        with pytest.raises(CharacterInventoryItem.DoesNotExist):
            action()


# --- spells ------------------------------------------------------------------------------------


def test_a_spell_is_added_prepared_and_marked_as_added_from_the_sheet(hero):
    row = play.add_spell(hero, "fireball")

    assert (row.prepared, row.always_prepared, row.source) == (True, False, play.SPELL_SOURCE)
    assert hero.spells.filter(spell_id="fireball").count() == 1
    with pytest.raises(ValueError):  # already there
        play.add_spell(hero, "fireball")
    with pytest.raises(Spell.DoesNotExist):
        play.add_spell(hero, "no-such-spell")


def test_only_a_spell_added_by_hand_can_be_removed_again(hero):
    play.add_spell(hero, "shield")
    CharacterSpell.objects.create(
        character=hero, spell=Spell.objects.get(pk="bless"), prepared=True, source="class:cleric"
    )

    play.remove_spell(hero, "shield")

    assert not hero.spells.filter(spell_id="shield").exists()
    with pytest.raises(ValueError):  # a class gave it: it stays
        play.remove_spell(hero, "bless")
    with pytest.raises(CharacterSpell.DoesNotExist):
        play.remove_spell(hero, "shield")

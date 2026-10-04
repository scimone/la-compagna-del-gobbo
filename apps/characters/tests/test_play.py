"""Play-state changes (`characters.services.play`): what the character sheet lets the owner tick."""

import pytest

from apps.builder.services import derived_stats
from apps.characters.models import (
    Character,
    CharacterClass,
    CharacterFeature,
    CharacterInventoryItem,
    CharacterResource,
    CharacterSpell,
)
from apps.characters.services import play
from apps.rules.models import Class, Equipment, Feat, Feature, OptionalFeature, Spell

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

    assert (row.prepared, row.always_prepared, row.source) == (True, True, play.SPELL_SOURCE)
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


def test_casting_follows_the_srd_slot_and_ritual_rules(hero):
    def learn(spell_id, **flags):
        CharacterSpell.objects.create(character=hero, spell=Spell.objects.get(pk=spell_id), **flags)

    learn("shield", prepared=True)
    learn("bless", in_spellbook=True)  # known but not prepared
    ritual = Spell.objects.filter(ritual=True, level=1).first()
    learn(ritual.pk, in_spellbook=True)

    play.cast_spell(hero, "shield", slot_key="2", slot_max=2, slot_level=2)  # upcast
    assert hero.spell_slots_spent == {"2": 1}
    with pytest.raises(ValueError):  # not prepared
        play.cast_spell(hero, "bless", slot_key="1", slot_max=2, slot_level=1)
    with pytest.raises(ValueError):  # slot too low
        play.cast_spell(hero, "shield", slot_key="1", slot_max=2, slot_level=0)
    play.cast_spell(hero, "shield", slot_key="2", slot_max=2, slot_level=2)
    with pytest.raises(ValueError):  # all spent
        play.cast_spell(hero, "shield", slot_key="2", slot_max=2, slot_level=2)
    # A ritual in the spellbook needs no preparation and no slot; a non-ritual cannot be one.
    assert play.cast_spell(hero, ritual.pk, ritual=True) == "ritual"
    with pytest.raises(ValueError):
        play.cast_spell(hero, "shield", ritual=True)


# --- features ----------------------------------------------------------------------------------


def test_a_feature_feat_and_option_are_added_and_marked_as_added_from_the_sheet(hero):
    feature = Feature.objects.filter(class_level__isnull=False).first()
    feat = Feat.objects.first()
    option = OptionalFeature.objects.first()

    assert play.add_feature(hero, "feature", str(feature.pk)) == feature
    assert play.add_feature(hero, "feat", feat.pk) == feat
    assert play.add_feature(hero, "option", option.pk) == option

    assert hero.features.get().source == play.FEATURE_SOURCE
    assert hero.feats.get().source == play.FEATURE_SOURCE
    assert hero.optional_features.get().source == play.FEATURE_SOURCE
    for kind, ref in (("feature", feature.pk), ("feat", feat.pk), ("option", option.pk)):
        with pytest.raises(ValueError):  # already there
            play.add_feature(hero, kind, str(ref))


def test_an_unknown_feature_or_kind_is_refused(hero):
    with pytest.raises(Feature.DoesNotExist):
        play.add_feature(hero, "feature", "0")
    with pytest.raises(Feat.DoesNotExist):
        play.add_feature(hero, "feat", "no-such-feat")
    with pytest.raises(ValueError):
        play.add_feature(hero, "spell", "fireball")


def test_only_a_feature_added_by_hand_can_be_removed_again(hero):
    added, granted = Feature.objects.filter(class_level__isnull=False)[:2]
    play.add_feature(hero, "feature", str(added.pk))
    CharacterFeature.objects.create(character=hero, feature=granted)

    play.remove_feature(hero, "feature", str(added.pk))

    assert not hero.features.filter(feature=added).exists()
    with pytest.raises(ValueError):  # the builder gave it: it stays
        play.remove_feature(hero, "feature", str(granted.pk))
    with pytest.raises(CharacterFeature.DoesNotExist):
        play.remove_feature(hero, "feature", str(added.pk))
    assert hero.features.filter(feature=granted).exists()


# --- rests -------------------------------------------------------------------------------------


@pytest.fixture
def fighter(hero):
    CharacterClass.objects.create(
        character=hero, klass=Class.objects.get(pk="fighter"), level=3, is_starting_class=True
    )
    CharacterResource.objects.create(
        character=hero, name="Second Wind", max_uses=2, current_uses=0, reset_on="other"
    )
    CharacterResource.objects.create(
        character=hero, name="Action Surge", max_uses=1, current_uses=0, reset_on="short_rest"
    )
    CharacterResource.objects.create(
        character=hero, name="Lay on Hands", max_uses=15, current_uses=3, reset_on="long_rest"
    )
    return hero


def test_a_short_rest_spends_hit_dice_to_heal_and_recharges_short_rest_abilities(fighter):
    fighter.current_hit_points = 5
    fighter.spell_slots_spent = {"pact": 1, "1": 2}
    fighter.save()

    healed = play.short_rest(fighter, [("d10", 6), ("d10", 6)], con_modifier=2)

    fighter.refresh_from_db()
    assert healed == 15 and fighter.current_hit_points == 20  # 2 x (6 + 2) capped at the max
    assert play.hit_dice_left(fighter) == {"d10": 1}
    assert fighter.spell_slots_spent == {"1": 2}  # only Pact Magic comes back
    resources = {r.name: r.current_uses for r in fighter.resources.all()}
    assert resources == {"Second Wind": 1, "Action Surge": 1, "Lay on Hands": 3}


def test_a_short_rest_die_heals_at_least_one_and_cannot_overspend(fighter):
    fighter.current_hit_points = 1
    fighter.save()

    assert play.short_rest(fighter, [("d10", 1)], con_modifier=-3) == 1
    with pytest.raises(ValueError):
        play.short_rest(fighter, [("d10", 4)] * 3, con_modifier=0)  # only 2 left
    with pytest.raises(ValueError):
        play.short_rest(fighter, [("d8", 1)], con_modifier=0)
    with pytest.raises(ValueError):
        play.short_rest(fighter, [("d10", 11)], con_modifier=0)  # a d10 rolls 1 to 10


def test_a_rest_needs_at_least_one_hit_point(fighter):
    fighter.current_hit_points = 0
    fighter.save()

    for rest in (lambda: play.short_rest(fighter, [], 0), lambda: play.long_rest(fighter)):
        with pytest.raises(ValueError):
            rest()


def test_a_long_rest_restores_everything_but_inspiration(fighter):
    fighter.current_hit_points = 4
    fighter.temporary_hit_points = 5
    fighter.death_save_failures = 2
    fighter.spell_slots_spent = {"1": 2, "pact": 1}
    fighter.inspiration = True
    fighter.save()
    fighter.classes.update(hit_dice_spent=2)
    CharacterSpell.objects.create(
        character=fighter,
        spell=Spell.objects.get(pk="shield"),
        prepared=True,
        free_cast=True,
        free_cast_used=True,
    )

    play.long_rest(fighter)

    fighter.refresh_from_db()
    assert (fighter.current_hit_points, fighter.temporary_hit_points) == (20, 0)
    assert fighter.death_save_failures == 0 and fighter.spell_slots_spent == {}
    assert fighter.inspiration is True
    assert play.hit_dice_left(fighter) == {"d10": 3}
    assert not fighter.spells.filter(free_cast_used=True).exists()
    assert all(r.current_uses == r.max_uses for r in fighter.resources.all())


def test_a_resource_is_spent_and_regained_between_zero_and_its_maximum(fighter):
    wind = fighter.resources.get(name="Second Wind")

    play.adjust_resource(fighter, wind.pk, 5)
    assert fighter.resources.get(name="Second Wind").current_uses == 2
    play.adjust_resource(fighter, wind.pk, -5)
    assert fighter.resources.get(name="Second Wind").current_uses == 0


def test_level_gain_opens_one_change_for_a_bard_and_each_change_uses_it_up(hero):
    CharacterClass.objects.filter(character=hero).delete()
    CharacterClass.objects.create(character=hero, klass=Class.objects.get(pk="bard"), level=3)
    for sid in ("bless", "shield"):
        CharacterSpell.objects.create(character=hero, spell_id=sid, klass_id="bard", prepared=True)
    with pytest.raises(ValueError):  # locked
        play.set_spell_prepared(hero, "bless", False, limit=4)

    play.grant_spell_changes(hero, "level", {"bard"})
    play.long_rest(hero)  # a Bard's window is a level, not a rest: untouched
    assert hero.spell_changes == {"bard": 1}
    play.set_spell_prepared(hero, "bless", False, limit=4)
    with pytest.raises(ValueError):  # the one change is spent
        play.set_spell_prepared(hero, "shield", False, limit=4)
    play.set_spell_prepared(hero, "bless", True, limit=4)  # filling a free slot costs nothing


def test_reductions_lower_the_maximum_and_the_scores_until_a_long_rest(fighter):
    fighter.current_hit_points = fighter.max_hit_points
    fighter.save()
    full = fighter.max_hit_points
    con = derived_stats.compute(fighter).abilities["str"]["score"]

    play.set_hit_point_reduction(fighter, 4)
    play.set_ability_reduction(fighter, "str", 3)
    fighter.refresh_from_db()
    assert fighter.hit_point_maximum == full - 4 and fighter.current_hit_points == full - 4
    play.adjust_hit_points(fighter, 99)
    assert fighter.current_hit_points == full - 4  # healing stops at the lowered maximum
    assert derived_stats.compute(fighter).abilities["str"]["score"] == con - 3

    play.long_rest(fighter)
    fighter.refresh_from_db()
    assert fighter.hit_point_maximum == full and fighter.current_hit_points == full
    assert fighter.ability_reductions == {}
    assert derived_stats.compute(fighter).abilities["str"]["score"] == con

"""Play-state changes on a finished character: HP, death saves, hit dice, spell slots, coins, worn
gear, free text, the items carried (add, count, remove, sell), the spells added by hand -
everything the character sheet lets the owner tick or type while playing.

Each function validates and clamps its input and saves; a value that makes no sense raises
`ValueError` (the view turns it into a 400). Rests (short/long) are not here yet.

An item row is one of two kinds, named `kind` in the functions that take a row id: `"catalog"` (a
`CharacterInventoryItem`) or `"custom"` (a `CharacterCustomItem`).
"""

from django.db import transaction

from apps.characters.models import (
    Character,
    CharacterCurrency,
    CharacterCustomItem,
    CharacterInventoryItem,
    CharacterSpell,
)
from apps.rules.models import Equipment, Spell

COINS = ("copper", "silver", "electrum", "gold", "platinum")
TEXT_FIELDS = ("backstory",)
DEATH_SAVES_MAX = 3
#: `rules.EquipmentType` ids. Only one body armor and one shield can be worn at a time.
BODY_ARMOR_TYPES = ("la", "ma", "ha")
SHIELD_TYPE = "s"
WEARABLE_TYPES = (*BODY_ARMOR_TYPES, SHIELD_TYPE, "m", "r")
#: Catalog types that keep their full value when sold ("Treasure"); everything else fetches half.
#: A custom item opts in with `valuable` (gems, art objects, trade goods).
FULL_VALUE_TYPES = ("c",)
CUSTOM_SECTIONS = tuple(key for key, _label in CharacterCustomItem.SECTION_CHOICES)
CUSTOM_WEAPON_CATEGORIES = tuple(key for key, _label in CharacterCustomItem.WEAPON_CATEGORY_CHOICES)
MAX_QUANTITY = 9999
#: `CharacterSpell.source` of a spell the player added from the sheet. The builder's grants carry
#: their own source, and only these can be taken away again from the sheet.
SPELL_SOURCE = "sheet"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def rename(character: Character, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("name is empty")
    character.name = name[: Character._meta.get_field("name").max_length]
    character.save(update_fields=["name", "updated_at"])


def set_experience(character: Character, xp: int) -> None:
    character.experience_points = max(0, xp)
    character.save(update_fields=["experience_points", "updated_at"])


def set_text(character: Character, field: str, text: str) -> None:
    if field not in TEXT_FIELDS:
        raise ValueError(f"unknown text field {field!r}")
    setattr(character, field, text)
    character.save(update_fields=[field, "updated_at"])


# --- hit points --------------------------------------------------------------------------------


def adjust_hit_points(character: Character, delta: int) -> None:
    """Damage (`delta < 0`) is taken from temporary hit points first, as the rules say; healing is
    capped at the maximum. Regaining hit points from 0 wipes the death saves."""
    was_down = character.current_hit_points == 0
    if delta < 0:
        absorbed = min(character.temporary_hit_points, -delta)
        character.temporary_hit_points -= absorbed
        delta += absorbed
    character.current_hit_points = _clamp(
        character.current_hit_points + delta, 0, character.max_hit_points
    )
    if was_down and character.current_hit_points > 0:
        character.death_save_successes = character.death_save_failures = 0
    character.save()


def set_hit_points(character: Character, value: int) -> None:
    """Set the current hit points outright (typed into the field): no temporary-HP absorption."""
    was_down = character.current_hit_points == 0
    character.current_hit_points = _clamp(value, 0, character.max_hit_points)
    if was_down and character.current_hit_points > 0:
        character.death_save_successes = character.death_save_failures = 0
    character.save()


def set_temporary_hit_points(character: Character, value: int) -> None:
    character.temporary_hit_points = max(0, value)
    character.save(update_fields=["temporary_hit_points", "updated_at"])


def toggle_death_save(character: Character, kind: str, index: int) -> None:
    """Tick the `index`-th (1-3) success or failure box; ticking the last ticked box again
    clears it, like un-checking a checkbox row."""
    if kind not in ("successes", "failures"):
        raise ValueError(f"unknown death save kind {kind!r}")
    field = f"death_save_{kind}"
    current = getattr(character, field)
    setattr(character, field, _clamp(index - 1 if current == index else index, 0, DEATH_SAVES_MAX))
    character.save(update_fields=[field, "updated_at"])


def set_inspiration(character: Character, value: bool) -> None:
    character.inspiration = value
    character.save(update_fields=["inspiration", "updated_at"])


# --- hit dice ----------------------------------------------------------------------------------


@transaction.atomic
def set_hit_dice_spent(character: Character, die: str, spent: int) -> None:
    """Set how many `die` (`"d10"`) Hit Dice are spent. The pool of one die size is spread over
    the classes that use it (each `CharacterClass` keeps its own count, as the SRD wants)."""
    rows = [c for c in character.classes.select_related("klass") if c.klass.hit_die == die]
    if not rows:
        raise ValueError(f"no {die} hit dice")
    remaining = _clamp(spent, 0, sum(c.level for c in rows))
    for row in rows:
        row.hit_dice_spent = min(row.level, remaining)
        remaining -= row.hit_dice_spent
        row.save(update_fields=["hit_dice_spent"])


# --- spell slots -------------------------------------------------------------------------------


def set_slots_spent(character: Character, key: str, spent: int, maximum: int) -> None:
    """`key` is a slot level (`"1"`..`"9"`) or `"pact"`; `maximum` is what the character has
    (derived from the class levels by the caller)."""
    if not (key == "pact" or key.isdigit()):
        raise ValueError(f"unknown slot {key!r}")
    slots = dict(character.spell_slots_spent)
    slots[key] = _clamp(spent, 0, maximum)
    character.spell_slots_spent = slots
    character.save(update_fields=["spell_slots_spent", "updated_at"])


# --- coins and gear ----------------------------------------------------------------------------


def set_coin(character: Character, coin: str, amount: int) -> None:
    if coin not in COINS:
        raise ValueError(f"unknown coin {coin!r}")
    purse, _created = CharacterCurrency.objects.get_or_create(character=character)
    setattr(purse, coin, max(0, amount))
    purse.save(update_fields=[coin])


def _purse_copper(purse: CharacterCurrency) -> int:
    """The whole purse, in copper."""
    return (
        purse.copper
        + purse.silver * 10
        + purse.electrum * 50
        + purse.gold * 100
        + purse.platinum * 1000
    )


def purse_copper(character: Character) -> int:
    """Everything in the character's coin purse, in copper (0 without one)."""
    purse = CharacterCurrency.objects.filter(character=character).first()
    return _purse_copper(purse) if purse else 0


def _set_purse_copper(purse: CharacterCurrency, total: int) -> None:
    """Re-mint `total` copper into coins. Platinum and electrum are kept only if the purse
    already uses them - like `sell_item`, a purchase never introduces a denomination the player
    never had."""
    remaining = total
    purse.platinum, remaining = divmod(remaining, 1000) if purse.platinum else (0, remaining)
    purse.electrum, remaining = divmod(remaining, 50) if purse.electrum else (0, remaining)
    purse.gold, remaining = divmod(remaining, 100)
    purse.silver, purse.copper = divmod(remaining, 10)
    purse.save(update_fields=["copper", "silver", "electrum", "gold", "platinum"])


@transaction.atomic
def set_equipped(character: Character, item_id: int, equipped: bool) -> None:
    """Wear or take off one item. Wearing body armor takes off the armor already worn, and a shield
    likewise - otherwise the sheet would silently pick one of two worn armors."""
    item = character.inventory_items.select_related("equipment").get(pk=item_id)
    type_id = item.equipment.type_id
    if type_id not in WEARABLE_TYPES:
        raise ValueError("this item cannot be worn or wielded")
    if equipped and type_id in (*BODY_ARMOR_TYPES, SHIELD_TYPE):
        same_slot = BODY_ARMOR_TYPES if type_id in BODY_ARMOR_TYPES else (SHIELD_TYPE,)
        CharacterInventoryItem.objects.filter(
            character=character, equipment__type_id__in=same_slot, equipped=True
        ).exclude(pk=item.pk).update(equipped=False)
    item.equipped = equipped
    item.save(update_fields=["equipped"])


# --- items: add, count, remove, sell -----------------------------------------------------------


def sale_price(value: int | None, quantity: int, *, full_value: bool) -> int:
    """Copper a stack fetches: half its cost (rounded down), or all of it for trade goods and
    valuables. An item with no cost fetches nothing."""
    total = (value or 0) * quantity
    return total if full_value else total // 2


def _row(character: Character, kind: str, item_id: int):
    """The catalog stack or custom item `item_id` of this character (`DoesNotExist` if it is not
    theirs)."""
    if kind == "catalog":
        return character.inventory_items.select_related("equipment").get(pk=item_id)
    if kind == "custom":
        return character.custom_items.get(pk=item_id)
    raise ValueError(f"unknown item kind {kind!r}")


def _unit_value(row) -> tuple[int | None, bool]:
    """`(cost in copper, sells for full value)` of one unit of a stack."""
    if isinstance(row, CharacterCustomItem):
        return row.value, row.valuable
    return row.equipment.value, row.equipment.type_id in FULL_VALUE_TYPES


def add_item(character: Character, equipment_id: str, quantity: int = 1) -> CharacterInventoryItem:
    """Put catalog gear in the inventory: onto the loose stack of the same item if there is one
    (not a pack's contents), otherwise as a new stack."""
    equipment = Equipment.objects.get(pk=equipment_id)
    quantity = _clamp(quantity, 1, MAX_QUANTITY)
    stack = character.inventory_items.filter(equipment=equipment, parent=None).first()
    if stack is None:
        return CharacterInventoryItem.objects.create(
            character=character, equipment=equipment, quantity=quantity
        )
    stack.quantity = _clamp(stack.quantity + quantity, 1, MAX_QUANTITY)
    stack.save(update_fields=["quantity"])
    return stack


@transaction.atomic
def buy_item(
    character: Character, equipment_id: str, quantity: int = 1
) -> tuple[CharacterInventoryItem, int]:
    """Pay catalog gear's cost out of the coin purse, then add it like `add_item`. Returns the
    item stack and the copper paid; an item with no price, or a purse that cannot afford it,
    refuses (nothing is charged or added)."""
    equipment = Equipment.objects.get(pk=equipment_id)
    quantity = _clamp(quantity, 1, MAX_QUANTITY)
    if not equipment.value:
        raise ValueError("this item has no price to buy it at")
    price = equipment.value * quantity
    purse, _created = CharacterCurrency.objects.get_or_create(character=character)
    if price > _purse_copper(purse):
        raise ValueError("not enough money to buy this")
    _set_purse_copper(purse, _purse_copper(purse) - price)
    return add_item(character, equipment_id, quantity), price


@transaction.atomic
def add_custom_item(
    character: Character,
    *,
    name: str,
    section: str = "misc",
    type_label: str = "",
    weapon_category: str = "",
    quantity: int = 1,
    weight: float | None = None,
    value: int | None = None,
    valuable: bool = False,
    description: str = "",
    buy: bool = False,
) -> CharacterCustomItem:
    """List an item of the player's own. With `buy`, its cost (`value` per unit, in copper) is
    also paid out of the coin purse - an item with no cost, or a purse that cannot afford it,
    refuses (nothing is charged or added); without, it is simply added (a gift, say)."""
    name = name.strip()
    if not name:
        raise ValueError("name is empty")
    if section not in CUSTOM_SECTIONS:
        raise ValueError(f"unknown section {section!r}")
    if weapon_category and weapon_category not in CUSTOM_WEAPON_CATEGORIES:
        raise ValueError(f"unknown weapon category {weapon_category!r}")
    if (weight is not None and weight < 0) or (value is not None and value < 0):
        raise ValueError("weight and cost cannot be negative")
    quantity = _clamp(quantity, 1, MAX_QUANTITY)
    if buy:
        if not value:
            raise ValueError("this item has no price to buy it at")
        purse, _created = CharacterCurrency.objects.get_or_create(character=character)
        if value * quantity > _purse_copper(purse):
            raise ValueError("not enough money to buy this")
        _set_purse_copper(purse, _purse_copper(purse) - value * quantity)
    type_max = CharacterCustomItem._meta.get_field("type_label").max_length
    return CharacterCustomItem.objects.create(
        character=character,
        name=name[: CharacterCustomItem._meta.get_field("name").max_length],
        section=section,
        type_label=type_label.strip()[:type_max],
        # Only weapons have one - a stray value from the client for any other section is dropped
        # rather than trusted, same spirit as `section` above.
        weapon_category=weapon_category if section == "weapons" else "",
        quantity=quantity,
        weight=weight or None,
        value=value or None,
        valuable=valuable,
        description=description.strip(),
    )


def set_item_quantity(character: Character, kind: str, item_id: int, quantity: int) -> None:
    """Change how many of an item there are (at least 1 - use `remove_item` to get rid of it)."""
    row = _row(character, kind, item_id)
    row.quantity = _clamp(quantity, 1, MAX_QUANTITY)
    row.save(update_fields=["quantity"])


def adjust_item_quantity(character: Character, kind: str, item_id: int, delta: int) -> None:
    row = _row(character, kind, item_id)
    set_item_quantity(character, kind, item_id, row.quantity + delta)


@transaction.atomic
def remove_item(character: Character, kind: str, item_id: int) -> None:
    row = _row(character, kind, item_id)
    parent_id = getattr(row, "parent_id", None)
    row.delete()
    # A pack is listed as its contents, so once the last of them is gone the empty pack row would
    # turn up as an item of its own.
    if parent_id and not CharacterInventoryItem.objects.filter(parent_id=parent_id).exists():
        CharacterInventoryItem.objects.filter(pk=parent_id).delete()


@transaction.atomic
def sell_item(character: Character, kind: str, item_id: int, quantity: int = 1) -> int:
    """Sell `quantity` of an item (all of them if that is more than there are) and pay the price
    into the coin purse. Returns the copper paid; an item with no cost cannot be sold."""
    row = _row(character, kind, item_id)
    quantity = _clamp(quantity, 1, row.quantity)
    value, full = _unit_value(row)
    price = sale_price(value, quantity, full_value=full)
    if not price:
        raise ValueError("this item has no value to sell for")
    purse, _created = CharacterCurrency.objects.get_or_create(character=character)
    gold, rest = divmod(price, 100)
    silver, copper = divmod(rest, 10)
    purse.gold += gold
    purse.silver += silver
    purse.copper += copper
    purse.save(update_fields=["gold", "silver", "copper"])
    if quantity >= row.quantity:
        remove_item(character, kind, item_id)
    else:
        row.quantity -= quantity
        row.save(update_fields=["quantity"])
    return price


# --- spells ------------------------------------------------------------------------------------


def add_spell(character: Character, spell_id: str) -> CharacterSpell:
    """Add a spell to the character's list, prepared. `Spell.DoesNotExist` for an unknown id,
    `ValueError` when the character already has it."""
    spell = Spell.objects.get(pk=spell_id)
    row, created = CharacterSpell.objects.get_or_create(
        character=character,
        spell=spell,
        defaults={"prepared": True, "source": SPELL_SOURCE},
    )
    if not created:
        raise ValueError(f"{spell.name} is already on the list")
    return row


def remove_spell(character: Character, spell_id: str) -> None:
    """Take away a spell added by hand (`add_spell`). One the character got from a class, species
    or feat is part of what it can do, and stays."""
    row = character.spells.get(spell_id=spell_id)
    if row.source != SPELL_SOURCE:
        raise ValueError("only a spell you added yourself can be removed")
    row.delete()

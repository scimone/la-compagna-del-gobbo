"""Play-state changes on a finished character: HP, death saves, hit dice, spell slots, coins, worn
gear, free text, the items carried (add, count, remove, sell), the spells and features added by
hand - everything the character sheet lets the owner tick or type while playing.

Each function validates and clamps its input and saves; a value that makes no sense raises
`ValueError` (the view turns it into a 400). Rests are at the end (`short_rest`, `long_rest`).

An item row is one of two kinds, named `kind` in the functions that take a row id: `"catalog"` (a
`CharacterInventoryItem`) or `"custom"` (a `CharacterCustomItem`).
"""

import json
import re

from django.db import models, transaction

from apps.builder.class_spec import CLASS_SPEC
from apps.builder.services import derived_stats
from apps.characters import conditions, custom_effects
from apps.characters.models import (
    Character,
    CharacterChoice,
    CharacterCurrency,
    CharacterCustomFeature,
    CharacterCustomItem,
    CharacterFeat,
    CharacterFeature,
    CharacterInventoryItem,
    CharacterOptionalFeature,
    CharacterResource,
    CharacterSpell,
    CustomCatalogItem,
)
from apps.rules.models import Equipment, Feat, Feature, OptionalFeature, Spell

COINS = ("copper", "silver", "electrum", "gold", "platinum")
_COIN_ABBR = {"copper": "cp", "silver": "sp", "electrum": "ep", "gold": "gp", "platinum": "pp"}
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
CUSTOM_ARMOR_KINDS = tuple(key for key, _label in CharacterCustomItem.ARMOR_KIND_CHOICES)
#: The `rules.EquipmentType` a custom armor kind counts as (Dex cap, proficiency, its slot).
CUSTOM_ARMOR_TYPE = {"light": "la", "medium": "ma", "heavy": "ha", "shield": SHIELD_TYPE}
CUSTOM_DAMAGE_TYPES = ("slashing", "piercing", "bludgeoning")
#: What `custom_wear_type` returns for an item worn for its effects alone (no weapon/armor stats).
CUSTOM_WORN = "worn"
MAX_QUANTITY = 9999
_DICE = re.compile(r"^\d{1,2}d\d{1,3}$")
_RANGE = re.compile(r"^\d{1,4}(/\d{1,4})?$")
#: `CharacterSpell.source` of a spell the player added from the sheet. The builder's grants carry
#: their own source, and only these can be taken away again from the sheet.
SPELL_SOURCE = "sheet"
#: The Druid's Wild Companion (level 2): Find Familiar cast with a slot or a use of Wild Shape.
#: A character that has the feature but no other way to Find Familiar gets the spell from it, with
#: this `CharacterSpell.source` - which is also how the sheet knows it has no ritual option.
WILD_COMPANION = "Wild Companion"
WILD_COMPANION_SPELL = "find-familiar"
WILD_COMPANION_SOURCE = "feature:wild-companion"
#: The source of a class-list spell that only got a row once prepared (`learn_class_spell`).
CLASS_SPELL_SOURCE = "class"
#: The same for a feature, feat or option the player added from the sheet (`add_feature`).
FEATURE_SOURCE = "sheet"
#: What `add_feature`/`remove_feature` take as `kind`, and the model each one is stored in.
FEATURE_KINDS = {
    "feature": (Feature, CharacterFeature, "feature"),
    "feat": (Feat, CharacterFeat, "feat"),
    "option": (OptionalFeature, CharacterOptionalFeature, "optional_feature"),
}


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
        character.current_hit_points + delta, 0, character.hit_point_maximum
    )
    if was_down and character.current_hit_points > 0:
        character.death_save_successes = character.death_save_failures = 0
    _sync_unconscious(character, was_down)
    character.save()


def set_hit_point_reduction(character: Character, value: int) -> None:
    """Lower the maximum hit points by `value` until the next Long Rest (the current ones follow
    the maximum down)."""
    character.max_hit_points_reduction = _clamp(value, 0, character.max_hit_points)
    character.current_hit_points = min(character.current_hit_points, character.hit_point_maximum)
    character.save()


def set_ability_reduction(character: Character, ability: str, value: int) -> None:
    """Lower an ability score (`"str"`...) by `value` until the next Long Rest."""
    fields = {
        "str": "strength",
        "dex": "dexterity",
        "con": "constitution",
        "int": "intelligence",
        "wis": "wisdom",
        "cha": "charisma",
    }
    if ability not in fields:
        raise ValueError(f"no ability {ability}")
    reductions = dict(character.ability_reductions or {})
    lost = _clamp(value, 0, getattr(character, fields[ability]))
    if lost:
        reductions[ability] = lost
    else:
        reductions.pop(ability, None)
    character.ability_reductions = reductions
    character.save()


def set_hit_points(character: Character, value: int) -> None:
    """Set the current hit points outright (typed into the field): no temporary-HP absorption."""
    was_down = character.current_hit_points == 0
    character.current_hit_points = _clamp(value, 0, character.hit_point_maximum)
    if was_down and character.current_hit_points > 0:
        character.death_save_successes = character.death_save_failures = 0
    _sync_unconscious(character, was_down)
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


def _store_condition(character: Character, condition_id: str, on: bool) -> None:
    """Change the stored list without saving. Putting a condition on also stores the ones that
    outlast it ("When this condition ends, you remain Prone"), so that they are still there
    when it is taken off."""
    current = [c for c in character.conditions if c != condition_id]
    if on:
        current.append(condition_id)
        for kept in conditions.BY_ID[condition_id].remains:
            if kept not in current:
                current.append(kept)
    character.conditions = current


def set_condition(character: Character, condition_id: str, on: bool) -> None:
    """Put a condition on the character or take it off (conditions don't stack: it is there or it
    isn't). Exhaustion has its own level, see `set_exhaustion()`."""
    if condition_id not in conditions.BY_ID:
        raise ValueError("unknown condition")
    _store_condition(character, condition_id, on)
    _end_wild_shape_if_down(character)
    character.save(update_fields=["conditions", "wild_shape_form"])


def _sync_unconscious(character: Character, was_down: bool) -> None:
    """The Handbook's "Falling Unconscious": at 0 hit points a character has the Unconscious
    condition until it regains any hit points. (Prone stays - see `_store_condition()`.)"""
    if character.current_hit_points < 1:
        if conditions.UNCONSCIOUS not in character.conditions:
            _store_condition(character, conditions.UNCONSCIOUS, True)
    elif was_down and conditions.UNCONSCIOUS in character.conditions:
        _store_condition(character, conditions.UNCONSCIOUS, False)
    _end_wild_shape_if_down(character)


def _end_wild_shape_if_down(character: Character) -> None:
    """Wild Shape ends when the Druid drops to 0 hit points or is Incapacitated (not saved here)."""
    if character.wild_shape_form and (
        character.current_hit_points < 1 or conditions.effects(character).incapacitated
    ):
        character.wild_shape_form = ""


def set_exhaustion(character: Character, level: int) -> None:
    character.exhaustion = _clamp(level, 0, conditions.EXHAUSTION_MAX)
    character.save(update_fields=["exhaustion"])


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


def add_coins(character: Character, coin: str, amount: int) -> None:
    """Put `amount` more `coin`s in the purse (loot, a reward, a gift)."""
    if coin not in COINS:
        raise ValueError(f"unknown coin {coin!r}")
    if amount < 1:
        raise ValueError("the amount must be at least 1")
    purse, _created = CharacterCurrency.objects.get_or_create(character=character)
    setattr(purse, coin, getattr(purse, coin) + amount)
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
def set_equipped(character: Character, item_id: int, equipped: bool, kind: str = "catalog") -> None:
    """Wear or take off one item. Wearing body armor takes off the armor already worn, and a shield
    likewise - otherwise the sheet would silently pick one of two worn armors. Catalog gear and
    custom items (`kind`) share those slots."""
    if kind == "custom":
        item = character.custom_items.get(pk=item_id)
        type_id = custom_wear_type(item)
    else:
        item = character.inventory_items.select_related("equipment").get(pk=item_id)
        type_id = item.equipment.type_id
    if type_id not in (*WEARABLE_TYPES, CUSTOM_WORN):
        raise ValueError("this item cannot be worn or wielded")
    if equipped and type_id in (*BODY_ARMOR_TYPES, SHIELD_TYPE):
        same_slot = BODY_ARMOR_TYPES if type_id in BODY_ARMOR_TYPES else (SHIELD_TYPE,)
        CharacterInventoryItem.objects.filter(
            character=character, equipment__type_id__in=same_slot, equipped=True
        ).exclude(pk=item.pk if kind == "catalog" else None).update(equipped=False)
        for other in character.custom_items.filter(equipped=True).exclude(
            pk=item.pk if kind == "custom" else None
        ):
            if custom_wear_type(other) in same_slot:
                other.equipped = False
                other.save(update_fields=["equipped"])
    item.equipped = equipped
    item.save(update_fields=["equipped"])
    if kind == "custom":
        sync_custom_spells(character)


def custom_wear_type(item: CharacterCustomItem) -> str:
    """The `EquipmentType` id a custom item is worn as, `""` when it cannot be worn: armor needs a
    kind and an AC, a weapon needs damage dice (melee `m`, or ranged `r`). Anything else is worn
    (`CUSTOM_WORN`) when it was made wearable or carries effects - it takes no slot."""
    if item.section == "armor" and item.armor_kind and item.ac:
        return CUSTOM_ARMOR_TYPE[item.armor_kind]
    if item.section == "weapons" and item.damage_dice:
        return "r" if item.ranged else "m"
    if item.section not in ("weapons", "armor") and (item.wearable or item.effects or item.spells):
        return CUSTOM_WORN
    return ""


# --- items: add, count, remove, sell -----------------------------------------------------------


def sale_price(value: int | None, quantity: int, *, full_value: bool) -> int:
    """Copper a stack fetches: half its cost (rounded down), or all of it for trade goods and
    valuables. An item with no cost fetches nothing."""
    total = (value or 0) * quantity
    return total if full_value else total // 2


#: The custom-item fields a catalog entry stores (everything `_clean_custom` takes).
CATALOG_FIELDS = (
    "name", "section", "type_label", "weapon_category", "weight", "value", "valuable",
    "description", "armor_kind", "ac", "strength_requirement", "stealth_disadvantage",
    "damage_dice", "damage_type", "versatile_damage_dice", "ranged", "finesse", "two_handed",
    "range", "wearable", "effects", "spells",
)  # fmt: skip


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
def merge_duplicate_items(character: Character) -> int:
    """Fold catalog stacks of the same item (and the same pack, or none) into one, adding up the
    quantities. A character never lists the same gear twice. Returns how many rows went away."""
    groups: dict[tuple, list[CharacterInventoryItem]] = {}
    for row in character.inventory_items.order_by("pk"):
        groups.setdefault((row.equipment_id, row.parent_id), []).append(row)
    merged = 0
    for rows in groups.values():
        keep, extra = rows[0], rows[1:]
        if not extra:
            continue
        keep.quantity = _clamp(sum(r.quantity for r in rows), 1, MAX_QUANTITY)
        keep.equipped = any(r.equipped for r in rows)
        keep.attuned = any(r.attuned for r in rows)
        keep.notes = next((r.notes for r in rows if r.notes), "")
        keep.save(update_fields=["quantity", "equipped", "attuned", "notes"])
        CharacterInventoryItem.objects.filter(pk__in=[r.pk for r in extra]).delete()
        merged += len(extra)
    return merged


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


def _dice(text: str, label: str) -> str:
    text = (text or "").strip().lower()
    if text and not _DICE.match(text):
        raise ValueError(f"{label} must look like 1d8")
    return text


MAX_CUSTOM_SPELLS = 20
#: `CharacterSpell.source` of a spell an item or feature of the player's own grants:
#: `custom:item:<pk>` (while that item is worn) / `custom:feature:<pk>` (always).
CUSTOM_SPELL_SOURCE = "custom:"
#: How a granted spell may be cast without a slot: never (""), once per long rest, once per short
#: rest, or as often as wanted.
FREE_CASTS = ("", "long", "short", "unlimited")


def clean_spells(raw) -> list[dict]:
    """The spells a custom item or feature grants, from what a form posts (a JSON list, or an
    already-parsed one) as `[{"id": spell id, "free": one of FREE_CASTS}]`. A bare id means no
    free cast. Each must be a real spell, listed once, in the order given."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("spells are not valid JSON") from None
    if not isinstance(raw, list) or len(raw) > MAX_CUSTOM_SPELLS:
        raise ValueError("too many spells")
    entries: dict[str, str] = {}
    for entry in raw:
        spell_id, free = (
            (str(entry.get("id", "")), str(entry.get("free", "")))
            if isinstance(entry, dict)
            else (str(entry), "")
        )
        if free not in FREE_CASTS:
            raise ValueError(f"unknown free cast {free!r}")
        entries.setdefault(spell_id, free)
    known = set(Spell.objects.filter(pk__in=entries).values_list("pk", flat=True))
    if len(known) != len(entries):
        raise ValueError("unknown spell")
    return [{"id": i, "free": free} for i, free in entries.items()]


def spell_entries(raw) -> list[dict]:
    """A stored `spells` value as `[{"id", "free"}]` (older rows hold bare ids)."""
    return [
        {"id": e["id"], "free": e.get("free", "")} if isinstance(e, dict) else {"id": e, "free": ""}
        for e in raw or []
    ]


def _free_flags(free: str) -> dict:
    return {
        "free_cast": free in ("long", "short"),
        "free_cast_recharge": "short" if free == "short" else "long",
        "free_cast_unlimited": free == "unlimited",
    }


def sync_custom_spells(character: Character) -> None:
    """Make the character's spells match what their own items and features grant: every spell of
    a custom feature, and of a custom item while it is worn, is a spell that is always prepared
    (and, if the grant says so, can be cast without a slot); one that is no longer granted goes
    (the player's own spells and a spell the character has from anywhere else are never touched
    or doubled)."""
    wanted: dict[str, tuple[str, str]] = {}
    for feature in character.custom_features.all():
        for entry in spell_entries(feature.spells):
            wanted.setdefault(
                entry["id"], (f"{CUSTOM_SPELL_SOURCE}feature:{feature.pk}", entry["free"])
            )
    for item in character.custom_items.filter(equipped=True):
        for entry in spell_entries(item.spells):
            wanted.setdefault(entry["id"], (f"{CUSTOM_SPELL_SOURCE}item:{item.pk}", entry["free"]))
    for row in character.spells.filter(source__startswith=CUSTOM_SPELL_SOURCE):
        if row.spell_id not in wanted:
            row.delete()
            continue
        source, free = wanted.pop(row.spell_id)
        flags = _free_flags(free)
        if row.source != source or any(getattr(row, k) != v for k, v in flags.items()):
            row.source = source
            for key, value in flags.items():
                setattr(row, key, value)
            if not (row.free_cast or row.free_cast_unlimited):
                row.free_cast_used = False
            row.save()
    have = set(character.spells.values_list("spell_id", flat=True))
    for spell_id, (source, free) in wanted.items():
        if spell_id not in have:
            CharacterSpell.objects.create(
                character=character,
                spell_id=spell_id,
                prepared=True,
                always_prepared=True,
                source=source,
                **_free_flags(free),
            )


def _clean_custom(
    *,
    name: str,
    section: str = "misc",
    type_label: str = "",
    weapon_category: str = "",
    weight: float | None = None,
    value: int | None = None,
    valuable: bool = False,
    description: str = "",
    armor_kind: str = "",
    ac: int | None = None,
    strength_requirement: int | None = None,
    stealth_disadvantage: bool = False,
    damage_dice: str = "",
    damage_type: str = "",
    versatile_damage_dice: str = "",
    ranged: bool = False,
    finesse: bool = False,
    two_handed: bool = False,
    range: str = "",  # noqa: A002 - the model's own field name
    wearable: bool = False,
    effects=None,
    spells=None,
) -> dict:
    """Validate a custom item's fields and return them as model fields. A stat that does not belong
    to the section (damage on a potion) is dropped rather than trusted, like `weapon_category`."""
    name = name.strip()
    if not name:
        raise ValueError("name is empty")
    if section not in CUSTOM_SECTIONS:
        raise ValueError(f"unknown section {section!r}")
    if weapon_category and weapon_category not in CUSTOM_WEAPON_CATEGORIES:
        raise ValueError(f"unknown weapon category {weapon_category!r}")
    if armor_kind and armor_kind not in CUSTOM_ARMOR_KINDS:
        raise ValueError(f"unknown armor kind {armor_kind!r}")
    if damage_type and damage_type not in CUSTOM_DAMAGE_TYPES:
        raise ValueError(f"unknown damage type {damage_type!r}")
    if (weight is not None and weight < 0) or (value is not None and value < 0):
        raise ValueError("weight and cost cannot be negative")
    if (ac is not None and not 0 <= ac <= 30) or (
        strength_requirement is not None and not 0 <= strength_requirement <= 30
    ):
        raise ValueError("armor class and strength must be between 0 and 30")
    range = (range or "").strip().replace(" ", "")  # noqa: A001
    if range and not _RANGE.match(range):
        raise ValueError("range must look like 80/320")
    field = CharacterCustomItem._meta.get_field
    weapon = section == "weapons"
    armor = section == "armor"
    return {
        "name": name[: field("name").max_length],
        "section": section,
        "type_label": type_label.strip()[: field("type_label").max_length],
        "weapon_category": weapon_category if weapon else "",
        "weight": weight or None,
        "value": value or None,
        "valuable": valuable,
        "description": description.strip(),
        "armor_kind": armor_kind if armor else "",
        "ac": (ac or None) if armor else None,
        "strength_requirement": (strength_requirement or None) if armor else None,
        "stealth_disadvantage": stealth_disadvantage if armor else False,
        "damage_dice": _dice(damage_dice, "damage") if weapon else "",
        "damage_type": damage_type if weapon else "",
        "versatile_damage_dice": _dice(versatile_damage_dice, "versatile damage") if weapon else "",
        "ranged": ranged if weapon else False,
        "finesse": finesse if weapon else False,
        "two_handed": two_handed if weapon else False,
        "range": range if weapon and ranged else "",
        "wearable": wearable if section not in ("weapons", "armor") else False,
        "effects": custom_effects.clean(effects, weapon=weapon),
        "spells": clean_spells(spells),
    }


@transaction.atomic
def add_custom_item(
    character: Character, *, quantity: int = 1, buy: bool = False, **fields
) -> CharacterCustomItem:
    """List an item of the player's own (`fields`: see `_clean_custom`). With `buy`, its cost
    (`value` per unit, in copper) is also paid out of the coin purse - an item with no cost, or a
    purse that cannot afford it, refuses (nothing is charged or added); without, it is simply
    added (a gift, say)."""
    clean = _clean_custom(**fields)
    quantity = _clamp(quantity, 1, MAX_QUANTITY)
    if buy:
        value = clean["value"]
        if not value:
            raise ValueError("this item has no price to buy it at")
        purse, _created = CharacterCurrency.objects.get_or_create(character=character)
        if value * quantity > _purse_copper(purse):
            raise ValueError("not enough money to buy this")
        _set_purse_copper(purse, _purse_copper(purse) - value * quantity)
    _remember_custom(character.campaign_id, clean)
    return CharacterCustomItem.objects.create(character=character, quantity=quantity, **clean)


def _remember_custom(
    campaign_id: int | None, clean: dict, old_name: str = ""
) -> CustomCatalogItem | None:
    """Keep a custom item in the campaign's permanent catalog (`CustomCatalogItem`): the entry
    with its name - or, when it was just renamed, with its `old_name` - takes the new values, else
    a new entry is made (a character outside any campaign has no catalog)."""
    if campaign_id is None:
        return None
    entries = CustomCatalogItem.objects.filter(campaign_id=campaign_id)
    entry = entries.filter(name__iexact=clean["name"]).first()
    if entry is None and old_name:
        entry = entries.filter(name__iexact=old_name).first()
    if entry is None:
        return entries.create(campaign_id=campaign_id, **clean)
    for key, value in clean.items():
        setattr(entry, key, value)
    entry.save()
    return entry


@transaction.atomic
def add_catalog_custom_item(
    character: Character, entry_id: int, *, quantity: int = 1, buy: bool = False
) -> CharacterCustomItem:
    """Put an entry of the campaign's custom catalog on the sheet, like `add_custom_item`."""
    entry = CustomCatalogItem.objects.get(pk=entry_id, campaign_id=character.campaign_id)
    fields = {f: getattr(entry, f) for f in CATALOG_FIELDS}
    return add_custom_item(character, quantity=quantity, buy=buy, **fields)


def update_custom_item(character: Character, item_id: int, **fields) -> CharacterCustomItem:
    """Change a custom item after it was made (the same fields as when it was added; quantity has
    its own control). An item that can no longer be worn - its section or stats changed - is taken
    off."""
    item = character.custom_items.get(pk=item_id)
    clean = _clean_custom(**fields)
    old_name = item.name
    for key, value in clean.items():
        setattr(item, key, value)
    if item.equipped and not custom_wear_type(item):
        item.equipped = False
    item.save()
    _remember_custom(character.campaign_id, clean, old_name)
    sync_custom_spells(character)
    return item


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
    if kind == "custom":
        sync_custom_spells(character)
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


@transaction.atomic
def transfer_items(
    character: Character,
    target: Character,
    picks: list[tuple[str, int, int]],
    coins: dict[str, int] | None = None,
) -> list[str]:
    """Hand items over to another character of the same campaign. `picks` are `(kind, item id,
    quantity)`; a quantity above what there is moves the whole stack. Catalog gear joins the loose
    stack of the same item on the other sheet; a custom item arrives as a copy, not worn. The
    items leave this sheet (a worn one is simply no longer worn). `coins` (`{coin: amount}`) moves
    money the same way, coin for coin - never more than the purse holds. Returns what moved, as
    `"Name x2"` / `"5 gp"` lines. Nothing moves if any pick is wrong."""
    if target.pk == character.pk:
        raise ValueError("choose another character")
    if target.campaign_id != character.campaign_id or target.status != Character.STATUS_COMPLETE:
        raise ValueError("that character cannot receive items")
    coins = {coin: amount for coin, amount in (coins or {}).items() if amount}
    if not picks and not coins:
        raise ValueError("no items chosen")
    if len({(kind, item_id) for kind, item_id, _qty in picks}) != len(picks):
        raise ValueError("an item was chosen twice")
    moved = []
    if coins:
        purse = CharacterCurrency.objects.filter(character=character).first()
        for coin, amount in coins.items():
            if coin not in COINS or amount < 1:
                raise ValueError(f"invalid amount of {coin}")
            if not purse or getattr(purse, coin) < amount:
                raise ValueError(f"not enough {coin}")
        for coin, amount in coins.items():
            set_coin(character, coin, getattr(purse, coin) - amount)
            add_coins(target, coin, amount)
            moved.append(f"{amount} {_COIN_ABBR[coin]}")
    for kind, item_id, quantity in picks:
        row = _row(character, kind, item_id)
        quantity = _clamp(quantity, 1, row.quantity)
        if isinstance(row, CharacterCustomItem):
            name = row.name
            copy = CharacterCustomItem(
                character=target,
                quantity=quantity,
                **{f: getattr(row, f) for f in CATALOG_FIELDS},
            )
            copy.save()
        else:
            name = row.equipment.name
            add_item(target, row.equipment_id, quantity)
        if quantity >= row.quantity:
            remove_item(character, kind, item_id)
        else:
            row.quantity -= quantity
            row.save(update_fields=["quantity"])
        moved.append(f"{name} x{quantity}" if quantity > 1 else name)
    return moved


# --- spells ------------------------------------------------------------------------------------


def add_spell(character: Character, spell_id: str, limits: dict | None = None) -> CharacterSpell:
    """Add a spell to the character's list. `Spell.DoesNotExist` for an unknown id, `ValueError`
    when the character already has it.

    `limits` is `{class id: how many spells it prepares}` for the character's classes that
    prepare spells (the caller has the derived stats). A spell on one of those classes' lists
    then follows that class's preparation: it is tied to the class (a Wizard's goes into the
    spellbook) and prepared only while the class has room for it. Any other spell is simply
    prepared.
    """
    spell = Spell.objects.get(pk=spell_id)
    klass_id, prepared, in_spellbook = None, True, False
    # Not on the list of a class that prepares spells: nothing to swap it for, so it stays
    # prepared whatever happens (a cantrip needs no preparing).
    always = spell.level > 0
    for class_id, limit in (limits or {}).items():
        row = character.classes.select_related("klass").filter(klass_id=class_id).first()
        if row and row.klass.name_en in (spell.classes or []):
            klass_id = class_id
            in_spellbook = class_id == "wizard"
            used = character.spells.filter(
                klass_id=class_id, prepared=True, always_prepared=False, spell__level__gt=0
            ).count()
            prepared = spell.level == 0 or used < limit
            always = False
            break
    # Find Familiar that only Wild Companion gave: now it is the player's own, ritual included.
    character.spells.filter(spell=spell, source=WILD_COMPANION_SOURCE).delete()
    row, created = CharacterSpell.objects.get_or_create(
        character=character,
        spell=spell,
        defaults={
            "prepared": prepared,
            "always_prepared": always,
            "klass_id": klass_id,
            "in_spellbook": in_spellbook,
            "source": SPELL_SOURCE,
        },
    )
    if not created:
        raise ValueError(f"{spell.name} is already on the list")
    return row


@transaction.atomic
def has_wild_companion(character: Character) -> bool:
    return character.features.filter(feature__name_en=WILD_COMPANION).exists()


def wild_shape_uses_left(character: Character) -> int:
    row = character.resources.filter(name="Wild Shape").first()
    return row.current_uses if row else 0


def sync_wild_companion(character: Character) -> None:
    """Give a Druid that has Wild Companion the Find Familiar spell it casts, unless the character
    already has the spell from somewhere else (then that row stays as it is, ritual included)."""
    if not has_wild_companion(character):
        return
    CharacterSpell.objects.get_or_create(
        character=character,
        spell_id=WILD_COMPANION_SPELL,
        defaults={
            "prepared": True,
            "always_prepared": True,
            "source": WILD_COMPANION_SOURCE,
            "klass_id": "druid",
        },
    )


def cast_spell(
    character: Character,
    spell_id: str,
    *,
    slot_key: str = "",
    slot_max: int = 0,
    slot_level: int = 0,
    ritual: bool = False,
    free: bool = False,
    wild_shape: bool = False,
) -> str:
    """Cast one of the character's spells, applying the SRD's spellcasting rules. Returns what was
    spent (`""`, `"cantrip"`, `"ritual"` or the slot key).

    - A cantrip (level 0) costs nothing.
    - A spell with the Ritual tag can be cast as a ritual: no slot, and it need not be prepared
      when it is in the spellbook (`in_spellbook`), but it takes 10 minutes longer and cannot be
      upcast.
    - A spell with a free cast (Magic Initiate's) can be cast once without a slot (`free`); the
      use comes back on a long rest (`long_rest`). So can one Circle spell (Natural Recovery), once
      among all of them.
    - Any other spell must be prepared (or always prepared) and expends one slot of the spell's
      level or higher - `slot_key` is the pool (`"1"`..`"9"` or `"pact"`), `slot_level` the level
      it casts at and `slot_max` how many slots the pool has (both derived by the caller).
    - Find Familiar with Wild Companion (`wild_shape`) expends a use of Wild Shape instead of a
      slot, prepared or not. When Wild Companion is the only way the character has the spell
      there is no ritual option.
    """
    if character.wild_shape_form:
        raise ValueError("a Wild Shape form cannot cast spells")
    row = character.spells.select_related("spell").get(spell_id=spell_id)
    spell = row.spell
    is_prepared = row.prepared or row.always_prepared
    if spell.level == 0:
        return "cantrip"
    if wild_shape:
        if spell.pk != WILD_COMPANION_SPELL or not has_wild_companion(character):
            raise ValueError(f"{spell.name} cannot be cast with Wild Shape")
        with transaction.atomic():
            uses = character.resources.select_for_update().filter(name="Wild Shape").first()
            if uses is None or uses.current_uses < 1:
                raise ValueError("no Wild Shape uses left")
            uses.current_uses -= 1
            uses.save(update_fields=["current_uses"])
        return "wild_shape"
    if ritual:
        if row.source == WILD_COMPANION_SOURCE:
            raise ValueError("Wild Companion gives no ritual casting")
        if not spell.ritual:
            raise ValueError(f"{spell.name} is not a ritual")
        if not (is_prepared or row.in_spellbook):
            raise ValueError(f"{spell.name} is not prepared")
        return "ritual"
    if not is_prepared:
        raise ValueError(f"{spell.name} is not prepared")
    if free:
        if row.free_cast_unlimited:
            pass  # an invocation's spell: never spent
        elif row.free_cast and not row.free_cast_used:
            row.free_cast_used = True
            row.save(update_fields=["free_cast_used"])
        elif is_circle_spell(row) and natural_free_cast_left(character):
            character.spell_recoveries_used = [*character.spell_recoveries_used, NATURAL_FREE_CAST]
            character.save(update_fields=["spell_recoveries_used"])
        else:
            raise ValueError(f"{spell.name} has no free cast left")
        return "free"
    if slot_level < spell.level:
        raise ValueError("the slot is too low for this spell")
    spent = int(character.spell_slots_spent.get(slot_key, 0))
    if spent >= slot_max:
        raise ValueError("no spell slot of that level left")
    set_slots_spent(character, slot_key, spent + 1, slot_max)
    return slot_key


#: The SRD's "Spell Preparation by Class" table: `class id -> (when the list can be changed,
#: how many spells)`. `when` is "rest" (finishing a Long Rest) or "level" (gaining a level); the
#: number is 1 or "any".
PREPARATION_CHANGES = {
    "bard": ("level", 1),
    "cleric": ("rest", "any"),
    "druid": ("rest", "any"),
    "paladin": ("rest", 1),
    "ranger": ("rest", 1),
    "sorcerer": ("level", 1),
    "warlock": ("level", 1),
    "wizard": ("rest", "any"),
}


def grant_spell_changes(character: Character, when: str, class_ids=None) -> None:
    """Open the window to change prepared spells: every class (or just `class_ids`) whose SRD rule
    is `when` ("rest" or "level") may now swap its allowed number of spells."""
    changes = dict(character.spell_changes)
    for class_id, (class_when, number) in PREPARATION_CHANGES.items():
        if class_when != when or (class_ids is not None and class_id not in class_ids):
            continue
        if character.classes.filter(klass_id=class_id).exists():
            changes[class_id] = number
    if changes != character.spell_changes:
        character.spell_changes = changes
        character.save(update_fields=["spell_changes"])


# --- weapon mastery ----------------------------------------------------------------------------

MASTERY_CHOICE = "class.weapon_mastery"


def decline_rest_window(character: Character, kind: str) -> None:
    """The player turned down a change a rest offered (prepared spells, a Weapon Mastery weapon,
    the land, a Wild Shape form): it is gone until the next rest or level opens it again."""
    if kind == "spells":
        character.spell_changes = {}
        fields = ["spell_changes"]
    elif kind == "mastery":
        character.weapon_mastery_changes = {}
        fields = ["weapon_mastery_changes"]
    elif kind in ("land", "wild_shape"):
        character.rest_choices = {k: v for k, v in character.rest_choices.items() if k != kind}
        fields = ["rest_choices"]
    else:
        raise ValueError("unknown choice")
    character.save(update_fields=fields)


def grant_weapon_mastery_changes(character: Character) -> None:
    """A Long Rest lets each class with Weapon Mastery change one of its weapon choices."""
    changes = {
        row.klass_id: 1
        for row in character.classes.all()
        if CLASS_SPEC.get(row.klass_id) and CLASS_SPEC[row.klass_id].weapon_mastery
    }
    if changes != character.weapon_mastery_changes:
        character.weapon_mastery_changes = changes
        character.save(update_fields=["weapon_mastery_changes"])


LAND_CHOICE_PREFIX, LAND_CHOICE_SUFFIX = "subclass.", ".land"


def grant_rest_choices(character: Character) -> None:
    """A Long Rest opens the choices that are made anew after it: today only Circle of the
    Land's land, for a character that has picked one."""
    has_land = CharacterChoice.objects.filter(
        character=character,
        key__startswith=LAND_CHOICE_PREFIX,
        key__endswith=LAND_CHOICE_SUFFIX,
    ).exists()
    choices = dict(character.rest_choices)
    if has_land:
        choices["land"] = True
    # Wild Shape: a Long Rest lets one known form be replaced (`builder/services/wild_shape.py`).
    if CharacterChoice.objects.filter(character=character, key="wild_shape.forms").exists():
        choices["wild_shape"] = True
    if choices != character.rest_choices:
        character.rest_choices = choices
        character.save(update_fields=["rest_choices"])


def mastery_weapons(character: Character, class_id: str) -> list[Equipment]:
    """The weapons `class_id` could choose Weapon Mastery for (its melee-only / proficient-only
    rule), by name."""
    spec = CLASS_SPEC[class_id].weapon_mastery
    weapons = list(
        Equipment.objects.filter(
            weapon_category__in=["simple", "martial"],
            type_id__in=["m"] if spec.melee_only else ["m", "r"],
            masteries__isnull=False,
        )
        .distinct()
        .order_by("name")
        .prefetch_related("properties")
    )
    if spec.proficient_only:
        held = character.proficiencies.filter(category="weapon").values_list("name", flat=True)
        proficiency = derived_stats.weapon_proficiency(held)
        weapons = [w for w in weapons if proficiency.covers(w)]
    return weapons


def swap_weapon_mastery(character: Character, old_id: str, new_id: str) -> None:
    """Change one Weapon Mastery weapon for another, using up the class's change from a Long
    Rest."""
    choice = CharacterChoice.objects.filter(character=character, key=MASTERY_CHOICE).first()
    chosen = list(choice.value) if choice else []
    if old_id not in chosen:
        raise ValueError("that weapon is not one of the mastered ones")
    if new_id in chosen:
        raise ValueError("that weapon is already mastered")
    for class_id in character.weapon_mastery_changes:
        if class_id in CLASS_SPEC and any(
            w.id == new_id for w in mastery_weapons(character, class_id)
        ):
            break
    else:
        raise ValueError("no weapon mastery change can take that weapon")
    del character.weapon_mastery_changes[class_id]
    character.save(update_fields=["weapon_mastery_changes"])
    choice.value = [new_id if w == old_id else w for w in chosen]
    choice.save(update_fields=["value"])


def learn_class_spell(
    character: Character, spell_id: str, class_id: str, max_level: int
) -> CharacterSpell:
    """Give the character a spell of one of its prepared-spell classes' lists, unprepared - what
    preparing a spell it has not "met" yet needs first (the spellbook lists every spell the class
    could prepare, not only the ones that already have a row). `max_level` is the highest spell
    level the class can cast. `ValueError` when the spell is not on the class's list, is a
    cantrip or is too high; a class that keeps a spellbook (the Wizard) learns spells another way.
    """
    spell = Spell.objects.get(pk=spell_id)
    klass = character.classes.select_related("klass").get(klass_id=class_id).klass
    if character.spells.filter(klass_id=class_id, in_spellbook=True).exists():
        raise ValueError(f"{spell.name} is not in the spellbook")
    if getattr(klass, "name_en", klass.name) not in (spell.classes or []):
        raise ValueError(f"{spell.name} is not a {klass.name} spell")
    if spell.level < 1 or spell.level > max_level:
        raise ValueError(f"{spell.name} is not a spell this class can prepare")
    row, _created = CharacterSpell.objects.get_or_create(
        character=character,
        spell=spell,
        defaults={"klass_id": class_id, "prepared": False, "source": CLASS_SPELL_SOURCE},
    )
    return row


def set_spell_prepared(
    character: Character, spell_id: str, prepared: bool, *, limit: int | None = None
) -> CharacterSpell:
    """Prepare or unprepare one of the character's spells (SRD "Preparing Spells").

    - Only a level 1+ spell is prepared; cantrips are always ready.
    - An always-prepared spell (a domain, oath or species spell...) cannot be unprepared, and does
      not count against the class's limit.
    - A class that keeps a spellbook (the Wizard) prepares only spells that are in it.
    - `limit` is how many spells the spell's class lets its member have prepared (the class table's
      "Prepared Spells" column - worked out by the caller, who has the derived stats): preparing
      one more than that is refused. A spell without a class has no limit.
    - Taking a spell off the list is a *change*: only while the class has some left (a long rest
      or a level opens them, see `grant_spell_changes`); each one used up is one fewer.
    """
    row = character.spells.select_related("spell").get(spell_id=spell_id)
    if row.spell.level == 0:
        raise ValueError(f"{row.spell.name} is a cantrip: it needs no preparing")
    if row.always_prepared:
        raise ValueError(f"{row.spell.name} is always prepared")
    if prepared and not row.prepared and row.klass_id:
        same_class = character.spells.filter(klass_id=row.klass_id)
        if not row.in_spellbook and same_class.filter(in_spellbook=True).exists():
            raise ValueError(f"{row.spell.name} is not in the spellbook")
        if limit is not None:
            count = same_class.filter(
                prepared=True, always_prepared=False, spell__level__gt=0
            ).count()
            if count >= limit:
                raise ValueError(f"already {limit} spells prepared")
    if not prepared and row.prepared and row.klass_id and limit is not None:
        left = character.spell_changes.get(row.klass_id)
        if not left:
            raise ValueError("prepared spells can only be changed after a rest or a level")
        if left != "any":
            if left <= 1:
                del character.spell_changes[row.klass_id]
            else:
                character.spell_changes[row.klass_id] = left - 1
            character.save(update_fields=["spell_changes"])
    row.prepared = prepared
    row.save(update_fields=["prepared"])
    return row


def remove_spell(character: Character, spell_id: str) -> None:
    """Take away a spell added by hand (`add_spell`). One the character got from a class, species
    or feat is part of what it can do, and stays."""
    row = character.spells.get(spell_id=spell_id)
    if row.source != SPELL_SOURCE:
        raise ValueError("only a spell you added yourself can be removed")
    row.delete()


# --- features ----------------------------------------------------------------------------------


def _feature_kind(kind: str):
    try:
        return FEATURE_KINDS[kind]
    except KeyError:
        raise ValueError(f"unknown feature kind: {kind!r}") from None


def add_feature(character: Character, kind: str, ref: str):
    """Give the character a class/subclass/species feature (`kind="feature"`, `ref` its id), a
    feat (`"feat"`) or an option such as an invocation (`"option"`). Returns the catalog row.
    `ObjectDoesNotExist` for an unknown one, `ValueError` for an unknown kind or when the
    character already has it."""
    catalog, model, field = _feature_kind(kind)
    entry = catalog.objects.get(pk=ref)
    # Not `get_or_create`: a feat can be taken more than once (see `CharacterFeat`), so there may
    # be several rows to find.
    if model.objects.filter(character=character, **{field: entry}).exists():
        raise ValueError(f"{entry.name} is already on the sheet")
    model.objects.create(character=character, **{field: entry}, source=FEATURE_SOURCE)
    return entry


def remove_feature(character: Character, kind: str, ref: str) -> None:
    """Take away a feature added by hand (`add_feature`). One the builder granted is part of what
    the character is, and stays."""
    _catalog, model, field = _feature_kind(kind)
    rows = model.objects.filter(character=character, **{f"{field}_id": ref})
    if not rows.exists():
        raise model.DoesNotExist
    if not rows.filter(source=FEATURE_SOURCE).exists():
        raise ValueError("only a feature you added yourself can be removed")
    rows.filter(source=FEATURE_SOURCE).delete()
    if kind == "feat":  # the spells it granted go with it (skills and tools it gave stay)
        character.spells.filter(source=f"feat:{ref}").delete()


def _clean_custom_feature(name: str, description: str = "", effects=None, spells=None) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("name is empty")
    return {
        "name": name[: CharacterCustomFeature._meta.get_field("name").max_length],
        "description": (description or "").strip(),
        "effects": custom_effects.clean(effects),
        "spells": clean_spells(spells),
    }


def add_custom_feature(character: Character, **fields) -> CharacterCustomFeature:
    """Give the character a feature of the player's own: a name, a description, the `effects`
    that are always in force (see `characters.custom_effects`) and the `spells` that are always
    prepared."""
    feature = CharacterCustomFeature.objects.create(
        character=character, **_clean_custom_feature(**fields)
    )
    sync_custom_spells(character)
    return feature


def update_custom_feature(
    character: Character, feature_id: int, **fields
) -> CharacterCustomFeature:
    feature = character.custom_features.get(pk=feature_id)
    for key, value in _clean_custom_feature(**fields).items():
        setattr(feature, key, value)
    feature.save()
    sync_custom_spells(character)
    return feature


def remove_custom_feature(character: Character, feature_id: int) -> None:
    character.custom_features.get(pk=feature_id).delete()
    sync_custom_spells(character)


# --- resources ---------------------------------------------------------------------------------


# --- rests -------------------------------------------------------------------------------------
#
# SRD "Riposo breve" / "Riposo lungo" (Rules Glossary). What is *not* tracked, so not handled here:
# the timing of an interrupted rest (initiative, a spell that is not a cantrip, damage, an hour of
# exertion - the player says whether the rest was completed; the long rest offers "interrupted",
# which grants the short rest's benefits when an hour had passed), exhaustion, and the 16 hours
# between long rests (game time, not real time). Reduced maximum hit points and ability scores are
# kept on the character and cleared by a long rest.


def hit_dice_left(character: Character) -> dict[str, int]:
    """Unspent Hit Dice by die size (`{"d8": 2}`), the pools of every class added together."""
    left: dict[str, int] = {}
    for row in character.classes.select_related("klass"):
        left[row.klass.hit_die] = left.get(row.klass.hit_die, 0) + row.level - row.hit_dice_spent
    return left


def _spent_hit_dice(character: Character, die: str) -> int:
    return sum(
        c.hit_dice_spent
        for c in character.classes.select_related("klass")
        if c.klass.hit_die == die
    )


#: The features that recover spent spell slots at a Short Rest, once per Long Rest:
#: `feature name -> class id` (whose level sets how many levels' worth come back).
SLOT_RECOVERY = {"Arcane Recovery": "wizard", "Natural Recovery": "druid"}
SLOT_RECOVERY_MAX_LEVEL = 5


def slot_recovery(character: Character) -> dict | None:
    """The slot recovery the character may use at this Short Rest: `{"name", "budget"}` (the
    combined slot level allowed: half the class level, rounded up), or None - not a Wizard or a
    Circle of the Land Druid, or already used since the last Long Rest."""
    for name, class_id in SLOT_RECOVERY.items():
        row = character.classes.filter(klass_id=class_id).first()
        if (
            row
            and name not in character.spell_recoveries_used
            and character.features.filter(feature__name_en=name).exists()
        ):
            return {"name": name, "budget": (row.level + 1) // 2}
    return None


#: Natural Recovery's other half: once until a Long Rest, one Circle spell (level 1+) is cast
#: without a slot. Kept in `spell_recoveries_used` beside the slot recovery, cleared by `long_rest`.
NATURAL_FREE_CAST = "Natural Recovery free cast"


def is_circle_spell(row: CharacterSpell) -> bool:
    return row.source.startswith("subclass:") and row.spell.level > 0


def natural_free_cast_left(character: Character) -> bool:
    """Whether the Natural Recovery free cast of a Circle spell is still there to use."""
    return (
        NATURAL_FREE_CAST not in character.spell_recoveries_used
        and character.features.filter(feature__name_en="Natural Recovery").exists()
    )


def _require_standing(character: Character) -> None:
    if character.current_hit_points < 1:
        raise ValueError("a character needs at least 1 hit point to begin a rest")


@transaction.atomic
def short_rest(
    character: Character,
    rolls: list[tuple[str, int]],
    con_modifier: int,
    recover: dict[str, int] | None = None,
) -> int:
    """Take a short rest (1 hour). Returns the hit points regained.

    `recover` (`{"1": 2, "3": 1}`: slot level -> how many) is the spell slots Arcane / Natural
    Recovery brings back: their combined level within the feature's budget, none above level 5,
    only ones that are spent.

    `rolls` is one `(die, result)` per Hit Die spent (`[("d8", 5), ("d8", 3)]`), the result being
    what the player rolled at the table: each heals that plus the Constitution modifier (at least
    1 hit point), up to the maximum. Then the abilities that recharge on a short rest do: a
    resource marked `short_rest` in full, one marked `other` (Rage, Second Wind: "regain one
    use") by one use, and Pact Magic slots in full.
    """
    _require_standing(character)
    left = hit_dice_left(character)
    spent: dict[str, int] = {}
    healed = 0
    for die, result in rolls:
        sides = int(die.removeprefix("d"))
        spent[die] = spent.get(die, 0) + 1
        if spent[die] > left.get(die, 0):
            raise ValueError(f"not enough {die} hit dice")
        if not 1 <= result <= sides:
            raise ValueError(f"a {die} rolls 1 to {sides}")
        room = character.hit_point_maximum - character.current_hit_points
        gained = min(max(1, result + con_modifier), room)
        character.current_hit_points += gained
        healed += gained
    for die, count in spent.items():
        set_hit_dice_spent(character, die, _spent_hit_dice(character, die) + count)
    if healed:
        character.death_save_successes = character.death_save_failures = 0
    slots = dict(character.spell_slots_spent)
    slots.pop("pact", None)
    if recover:
        feature = slot_recovery(character)
        if feature is None:
            raise ValueError("no spell slot recovery to use")
        total = 0
        for key, count in recover.items():
            if not key.isdigit() or not 1 <= int(key) <= SLOT_RECOVERY_MAX_LEVEL or count < 0:
                raise ValueError(f"cannot recover a {key} slot")
            if count > int(slots.get(key, 0)):
                raise ValueError(f"not that many spent level {key} slots")
            total += int(key) * count
        if total > feature["budget"]:
            raise ValueError(f"only {feature['budget']} levels of slots can be recovered")
        for key, count in recover.items():
            slots[key] = int(slots.get(key, 0)) - count
        if total:
            character.spell_recoveries_used = [*character.spell_recoveries_used, feature["name"]]
    character.spell_slots_spent = slots
    character.use_flags = {k: v for k, v in character.use_flags.items() if v != "short"}
    # Tireless (Ranger 10): each Short Rest lowers the Exhaustion level by 1.
    if character.exhaustion and character.features.filter(feature__name_en="Tireless").exists():
        character.exhaustion -= 1
    character.save()
    character.spells.filter(free_cast_used=True, free_cast_recharge="short").update(
        free_cast_used=False
    )
    for row in character.resources.all():
        if row.reset_on == "short_rest":
            row.current_uses = row.max_uses
        elif row.reset_on == "other":
            row.current_uses = min(row.max_uses, row.current_uses + 1)
        else:
            continue
        row.save(update_fields=["current_uses"])
    return healed


@transaction.atomic
def long_rest(character: Character) -> None:
    """Take a long rest (8 hours): every hit point and every
    spent Hit Die back, temporary hit points gone, the death saves cleared, every spell slot and
    free cast (Magic Initiate's) and every limited-use resource restored.
    Heroic Inspiration is not touched."""
    _require_standing(character)
    character.max_hit_points_reduction = 0
    character.ability_reductions = {}
    character.created_slots = {}  # slots a feature made vanish
    character.use_flags = {}
    character.wild_shape_form = ""
    character.spell_recoveries_used = []
    character.exhaustion = max(0, character.exhaustion - 1)
    character.current_hit_points = character.hit_point_maximum
    character.temporary_hit_points = 0
    character.death_save_successes = character.death_save_failures = 0
    character.spell_slots_spent = {}
    character.save()
    character.classes.update(hit_dice_spent=0)
    character.spells.filter(free_cast_used=True).update(free_cast_used=False)
    grant_spell_changes(character, "rest")
    grant_weapon_mastery_changes(character)
    grant_rest_choices(character)
    CharacterResource.objects.filter(character=character).update(current_uses=models.F("max_uses"))

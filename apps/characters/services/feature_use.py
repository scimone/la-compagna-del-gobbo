"""Using a feature: what its "Use" button spends and does.

A feature card with a counter (`CharacterResource`) gets a Use button that spends it
(`play.use_resource`). This module is the table behind it (`use_for()`, `parts_for()`) and what the
button does (`available()`, `ask()`, `perform()`):

- a feature whose name is its counter spends one use of it (Rage, Second Wind, Breath Weapon ...);
- a feature that spends *another* feature's counter does so at its cost: Channel Divinity effects,
  Focus Point features, Bardic Inspiration reactions, Maneuvers, Metamagic (`SPENDS`);
- a feature whose text lists several options that each spend the counter is split into one card per
  option (`PARTS`: "Monk's Focus: Flurry of Blows") and the feature itself has no button;
- a feature that gives counters or spell slots back (Font of Magic, Sorcerous Restoration, Uncanny
  Metabolism, Persistent Rage, Wild Resurgence ...) does it as an `effect`.

Uses only come back by resting or by those effects - the player never sets a counter by hand. A
button is offered only while the use is possible (`available()`).
"""

import math
import re
from dataclasses import dataclass

from django.db import transaction
from django.utils.translation import gettext as _

from apps.characters.models import Character, CharacterResource
from apps.characters.services import play

SORCERY, FOCUS, WILD_SHAPE = "Sorcery Points", "Focus Points", "Wild Shape"
BARDIC, CHANNEL, RAGE = "Bardic Inspiration", "Channel Divinity", "Rage"
PSIONIC, SUPERIORITY = "Psionic Power", "Superiority Dice"


@dataclass(frozen=True)
class Use:
    #: The counter spent ("" when the use costs nothing but may need an effect).
    resource: str = ""
    cost: int = 1
    #: What it does besides spending: a key of `_EFFECTS`.
    effect: str = ""
    #: What the player is asked first: "points" (how many), "slot", "create_slot", "uses", "roll".
    ask: str = ""
    ask_max: int = 0
    #: `(flag, "short" | "long")`: the first use after that rest costs nothing (see `use_flags`).
    free: tuple = ()


#: Features that never have a button of their own although they carry a counter: their effects have
#: cards (or, for Arcane Recovery, the short rest dialog does it).
NO_BUTTON = {"Arcane Recovery", WILD_SHAPE, CHANNEL, "Combat Superiority", "Giant Ancestry"}

#: Features that spend another feature's counter (or one of their own at a different cost).
SPENDS: dict[str, Use] = {
    # Channel Divinity effects
    **{
        name: Use(CHANNEL)
        for name in (
            "Abjure Foes",
            "Preserve Life",
            "Radiance of the Dawn",
            "Invoke Duplicity",
            "War God's Blessing",
            "Guided Strike",
            "Sacred Weapon",
            "Inspiring Smite",
            "Peerless Athlete",
            "Nature's Wrath",
            "Vow of Enmity",
            "Divine Sense",
        )
    },
    # Bardic Inspiration
    **{
        name: Use(BARDIC)
        for name in (
            "Inspiring Movement",
            "Tandem Footwork",
            "Mantle of Inspiration",
            "Peerless Skill",
            "Cutting Words",
        )
    },
    # Focus Points
    "Deflect Attacks": Use(FOCUS),
    "Stunning Strike": Use(FOCUS),
    "Disciplined Survivor": Use(FOCUS),
    "Superior Defense": Use(FOCUS, 3),
    "Hand of Harm": Use(FOCUS),
    "Hand of Healing": Use(FOCUS),
    "Improved Shadow Step": Use(FOCUS),
    "Cloak of Shadows": Use(FOCUS, 3),
    "Shadow Arts": Use(FOCUS),
    "Elemental Burst": Use(FOCUS, 2),
    "Elemental Attunement": Use(FOCUS),
    "Quivering Palm": Use(FOCUS, 4),
    # Sorcery Points: 1 to 5 points go into the ward
    "Bastion of Law": Use(SORCERY, 1, ask="points", ask_max=5),
}

#: Features that do something besides spending (give back counters or slots).
EFFECTS: dict[str, Use] = {
    "Sorcerous Restoration": Use("Sorcerous Restoration", effect="restoration"),
    "Uncanny Metabolism": Use("Uncanny Metabolism", effect="uncanny", ask="roll"),
    "Perfect Focus": Use(effect="perfect_focus"),
    "Persistent Rage": Use("Persistent Rage", effect="persistent_rage"),
    "Superior Inspiration": Use(effect="superior_inspiration"),
    "Font of Inspiration": Use(effect="slot_to_bardic", ask="slot"),
    "Magical Cunning": Use("Magical Cunning", effect="magical_cunning"),
}

#: Features split into one card per option: `(feature, owner) -> [(option name, Use)]`. The owner
#: is the class id, the subclass name or the species id the feature comes from (`""` = any).
PARTS: dict[tuple[str, str], list[tuple[str, Use]]] = {
    ("Monk's Focus", ""): [
        (name, Use(FOCUS)) for name in ("Flurry of Blows", "Patient Defense", "Step of the Wind")
    ],
    ("Channel Divinity", "cleric"): [
        (name, Use(CHANNEL)) for name in ("Divine Spark", "Turn Undead")
    ],
    ("Celestial Revelation", ""): [
        (name, Use("Celestial Revelation"))
        for name in ("Heavenly Wings", "Inner Radiance", "Necrotic Shroud")
    ],
    ("The Third Eye", ""): [
        (name, Use("The Third Eye"))
        for name in ("Darkvision", "Greater Comprehension", "See Invisibility")
    ],
    ("Psionic Power", "Psi Warrior"): [
        ("Protective Field", Use(PSIONIC)),
        ("Psionic Strike", Use(PSIONIC)),
        ("Telekinetic Movement", Use(PSIONIC, free=("telekinetic_movement", "short"))),
    ],
    ("Psionic Power", "Soulknife"): [
        ("Psi-Bolstered Knack", Use(PSIONIC)),
        ("Psychic Whispers", Use(PSIONIC, free=("psychic_whispers", "long"))),
    ],
    ("Soul Blades", ""): [
        ("Homing Strikes", Use(PSIONIC)),
        ("Psychic Teleportation", Use(PSIONIC)),
    ],
    ("Font of Magic", ""): [
        ("Converting Spell Slots to Sorcery Points", Use(effect="slot_to_points", ask="slot")),
        ("Creating Spell Slots", Use(effect="create_slot", ask="create_slot")),
    ],
    ("Wild Resurgence", ""): [
        ("Wild Shape from a Spell Slot", Use(effect="slot_to_wild_shape", ask="slot")),
        ("Spell Slot from Wild Shape", Use("Wild Resurgence", effect="wild_to_slot")),
    ],
    ("Archdruid", ""): [
        ("Evergreen Wild Shape", Use(effect="evergreen")),
        ("Nature Magician", Use("Archdruid", effect="nature_magician", ask="uses")),
    ],
}

#: Creating Spell Slots (Font of Magic): slot level -> (Sorcery Point cost, minimum Sorcerer level).
CREATING = {1: (2, 2), 2: (3, 3), 3: (5, 5), 4: (6, 7), 5: (7, 9)}
#: Pools of points (Use asks how many) rather than uses.
POOLS = {"Lay on Hands", SORCERY, FOCUS}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def owner_keys(feature) -> set[str]:
    """What a `rules.Feature` belongs to: its class id, its subclass's name, its species id."""
    keys = set()
    if feature.class_level_id:
        keys.add(feature.class_level.klass_id)
    if feature.subclass_level_id:
        keys.add(feature.subclass_level.subclass.name_en)
    if feature.species_id:
        keys.add(feature.species_id)
    return keys


def parts_for(feature) -> list[tuple[str, Use]]:
    """The options a feature is split into (`[]` when it is not)."""
    name = feature.name_en.split(" (")[0]
    keys = owner_keys(feature)
    for (part_name, owner), parts in PARTS.items():
        if part_name == name and (not owner or owner in keys):
            return parts
    return []


def use_for(feature, resources: set[str]) -> Use | None:
    """What the feature's own Use button does, or None when it has none (it has no counter, or it
    is split into parts)."""
    name = feature.name_en.split(" (")[0]
    if name in NO_BUTTON or parts_for(feature):
        return None
    if name in EFFECTS:
        return EFFECTS[name]
    if name in SPENDS:
        return SPENDS[name]
    if name in resources:
        if name in POOLS:
            return Use(name, ask="points")
        return Use(name)
    return None


def option_use(feature_type: str, text: str) -> Use | None:
    """Maneuvers spend a Superiority Die, Metamagic options Sorcery Points (cost in the text)."""
    if feature_type.startswith("Maneuver"):
        return Use(SUPERIORITY)
    if feature_type == "Metamagic":
        found = re.search(r"(\d+) Sorcery Point", text)
        return Use(SORCERY, int(found.group(1)) if found else 1)
    return None


# --- state helpers -----------------------------------------------------------------------------


def _row(character: Character, name: str) -> CharacterResource | None:
    return character.resources.filter(name=name).first()


def left(character: Character, name: str) -> int:
    row = _row(character, name)
    return row.current_uses if row else 0


def maximum(character: Character, name: str) -> int:
    row = _row(character, name)
    return row.max_uses if row else 0


def _spend(character: Character, name: str, amount: int) -> None:
    row = _row(character, name)
    if row is None or row.current_uses < amount:
        raise ValueError(_("Not enough %(name)s left.") % {"name": name})
    row.current_uses -= amount
    row.save(update_fields=["current_uses"])


def _gain(character: Character, name: str, amount: int) -> int:
    """Give back up to `amount` of a counter, never above its maximum; how many came back."""
    row = _row(character, name)
    if row is None:
        return 0
    gained = max(0, min(amount, row.max_uses - row.current_uses))
    row.current_uses += gained
    row.save(update_fields=["current_uses"])
    return gained


def _class_level(character: Character, class_id: str) -> int:
    row = character.classes.filter(klass_id=class_id).first()
    return row.level if row else 0


def _pool(pools: list[dict], key: str) -> dict | None:
    return next((p for p in pools if p["key"] == key), None)


def _slot_levels(pools: list[dict]) -> list[dict]:
    """The slot pools with a slot left, not Pact Magic's."""
    return [p for p in pools if p["key"] != "pact" and p["left"] > 0]


def _spend_slot(character: Character, pools: list[dict], key: str) -> dict:
    pool = _pool(pools, key)
    if pool is None or key == "pact" or pool["left"] < 1:
        raise ValueError(_("No spell slot of that level left."))
    play.set_slots_spent(character, key, pool["spent"] + 1, pool["max"])
    return pool


def _add_created_slot(character: Character, level: int) -> None:
    slots = dict(character.created_slots)
    slots[str(level)] = int(slots.get(str(level), 0)) + 1
    character.created_slots = slots
    character.save(update_fields=["created_slots"])


def martial_arts_die(character: Character) -> int:
    from apps.rules.models import ClassLevel

    level = _class_level(character, "monk")
    row = ClassLevel.objects.filter(klass_id="monk", level=level).first()
    dice = (row.columns.get("Martial Arts") or {}) if row else {}
    return int((dice.get("toRoll") or [{"faces": 6}])[0]["faces"])


def free_available(character: Character, use: Use) -> bool:
    return bool(use.free) and use.free[0] not in character.use_flags


# --- is it possible, what to ask ---------------------------------------------------------------


def available(character: Character, use: Use, pools: list[dict]) -> bool:
    """Whether the Use button is worth showing now."""
    if use.free and free_available(character, use):
        return True
    if use.resource and left(character, use.resource) < max(1, use.cost):
        return False
    e = use.effect
    if e == "restoration":
        return left(character, SORCERY) < maximum(character, SORCERY)
    if e == "perfect_focus":
        return left(character, FOCUS) < min(4, maximum(character, FOCUS))
    if e == "persistent_rage":
        return left(character, RAGE) < maximum(character, RAGE)
    if e == "superior_inspiration":
        return left(character, BARDIC) < min(2, maximum(character, BARDIC))
    if e == "slot_to_bardic":
        return bool(_slot_levels(pools)) and left(character, BARDIC) < maximum(character, BARDIC)
    if e == "slot_to_points":
        return bool(_slot_levels(pools)) and left(character, SORCERY) < maximum(character, SORCERY)
    if e == "create_slot":
        return bool(_creatable(character))
    if e == "magical_cunning":
        pact = _pool(pools, "pact")
        return bool(pact and pact["spent"] > 0)
    if e == "evergreen":
        return maximum(character, WILD_SHAPE) > 0 and left(character, WILD_SHAPE) == 0
    if e == "slot_to_wild_shape":
        return (
            maximum(character, WILD_SHAPE) > 0
            and left(character, WILD_SHAPE) == 0
            and bool(_slot_levels(pools))
        )
    if e in ("wild_to_slot", "nature_magician"):
        return left(character, WILD_SHAPE) >= 1
    return True


def _creatable(character: Character) -> dict[int, int]:
    """`{slot level: Sorcery Point cost}` of the slots the Sorcerer may create now."""
    level = _class_level(character, "sorcerer")
    points = left(character, SORCERY)
    return {n: cost for n, (cost, at) in CREATING.items() if level >= at and points >= cost}


def ask(character: Character, use: Use, pools: list[dict]) -> dict | None:
    """What the player is asked before the use: `{"param", "label", "min", "max"}` for a number or
    `{"param", "label", "choices": [[value, label]]}` for a pick, else None."""
    kind = use.ask
    if not kind:
        return None
    if kind == "points":
        top = min(use.ask_max or 10**6, left(character, use.resource))
        label = _("How many points of %(name)s? (%(n)d left)") % {
            "name": use.resource,
            "n": left(character, use.resource),
        }
        return {"param": "amount", "label": label, "min": 1, "max": top}
    if kind == "roll":
        die = martial_arts_die(character)
        return {
            "param": "roll",
            "label": _("Roll your Martial Arts die (d%(n)d). What did you get?") % {"n": die},
            "min": 1,
            "max": die,
        }
    if kind == "uses":
        top = min(left(character, WILD_SHAPE), 4)
        return {
            "param": "uses",
            "label": _(
                "How many Wild Shape uses to convert? Each gives 2 spell levels (%(n)d left)"
            )
            % {"n": left(character, WILD_SHAPE)},
            "min": 1,
            "max": top,
        }
    if kind == "slot":
        return {
            "param": "slot",
            "label": _("Which spell slot do you expend?"),
            "choices": [
                [
                    p["key"],
                    _("Level %(level)d (%(n)d left)") % {"level": p["level"], "n": p["left"]},
                ]
                for p in _slot_levels(pools)
            ],
        }
    if kind == "create_slot":
        return {
            "param": "slot",
            "label": _("Which spell slot do you create? (%(n)d Sorcery Points left)")
            % {"n": left(character, SORCERY)},
            "choices": [
                [str(n), _("Level %(level)d (%(cost)d points)") % {"level": n, "cost": cost}]
                for n, cost in _creatable(character).items()
            ],
        }
    return None


def confirm_text(character: Character, name: str, use: Use) -> str:
    """What the confirmation modal says: what is spent and how much is left."""
    if use.free and free_available(character, use):
        return _("Use %(name)s? This one is free (once until your next rest).") % {"name": name}
    if use.resource:
        have = left(character, use.resource)
        return _(
            "Use %(name)s? This spends %(cost)d of %(resource)s (%(have)d of %(max)d left)."
        ) % {
            "name": name,
            "cost": use.cost,
            "resource": use.resource,
            "have": have,
            "max": maximum(character, use.resource),
        }
    return _("Use %(name)s?") % {"name": name}


# --- doing it ----------------------------------------------------------------------------------


def _int(params, key: str, default: int = 0) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"{key} is not a number") from None


@transaction.atomic
def perform(character: Character, name: str, use: Use, params, pools: list[dict]) -> str:
    """Do the use: spend what it costs and apply its effect. `params` is what the player was asked
    (`ask()`). Returns a line for the toast; `ValueError` when it cannot be done."""
    if not available(character, use, pools):
        raise ValueError(_("You can't use %(name)s now.") % {"name": name})
    e = use.effect
    note = ""
    # Spending: the first use of a free ability costs nothing.
    if use.free and free_available(character, use):
        flags = dict(character.use_flags)
        flags[use.free[0]] = use.free[1]
        character.use_flags = flags
        character.save(update_fields=["use_flags"])
    elif use.resource:
        amount = use.cost
        if use.ask == "points":
            amount = _int(params, "amount", 1)
            if not 1 <= amount <= (use.ask_max or amount):
                raise ValueError("invalid amount")
        _spend(character, use.resource, amount)
    if e:
        note = _EFFECTS[e](character, params, pools)
    return note or _("Used %(name)s") % {"name": name}


def _restoration(character, params, pools) -> str:
    half = _class_level(character, "sorcerer") // 2
    gained = _gain(character, SORCERY, half)
    return _("You regain %(n)d Sorcery Points") % {"n": gained}


def _uncanny(character, params, pools) -> str:
    roll = _int(params, "roll", 0)
    if not 1 <= roll <= martial_arts_die(character):
        raise ValueError("invalid roll")
    row = _row(character, FOCUS)
    regained = 0
    if row:
        regained = row.max_uses - row.current_uses
        row.current_uses = row.max_uses
        row.save(update_fields=["current_uses"])
    heal = _class_level(character, "monk") + roll
    play.adjust_hit_points(character, heal)
    return _("You regain %(fp)d Focus Points and %(hp)d hit points") % {"fp": regained, "hp": heal}


def _perfect_focus(character, params, pools) -> str:
    row = _row(character, FOCUS)
    target = min(4, row.max_uses)
    gained = _gain(character, FOCUS, target - row.current_uses)
    return _("You regain %(n)d Focus Points") % {"n": gained}


def _persistent_rage(character, params, pools) -> str:
    gained = _gain(character, RAGE, 10**6)
    return _("You regain %(n)d uses of Rage") % {"n": gained}


def _superior_inspiration(character, params, pools) -> str:
    row = _row(character, BARDIC)
    gained = _gain(character, BARDIC, min(2, row.max_uses) - row.current_uses)
    return _("You regain %(n)d uses of Bardic Inspiration") % {"n": gained}


def _slot_to_bardic(character, params, pools) -> str:
    _spend_slot(character, pools, str(params.get("slot", "")))
    _gain(character, BARDIC, 1)
    return _("You regain one use of Bardic Inspiration")


def _magical_cunning(character, params, pools) -> str:
    pact = _pool(pools, "pact")
    back = min(pact["spent"], math.ceil(pact["max"] / 2))
    play.set_slots_spent(character, "pact", pact["spent"] - back, pact["max"])
    return _("You regain %(n)d Pact Magic slots") % {"n": back}


def _slot_to_points(character, params, pools) -> str:
    pool = _spend_slot(character, pools, str(params.get("slot", "")))
    gained = _gain(character, SORCERY, pool["level"])
    return _("You gain %(n)d Sorcery Points") % {"n": gained}


def _create_slot(character, params, pools) -> str:
    level = _int(params, "slot")
    cost = _creatable(character).get(level)
    if cost is None:
        raise ValueError(_("You can't create that spell slot."))
    _spend(character, SORCERY, cost)
    _add_created_slot(character, level)
    return _("You create a level %(level)d spell slot until your next long rest") % {"level": level}


def _evergreen(character, params, pools) -> str:
    _gain(character, WILD_SHAPE, 1)
    return _("You regain one use of Wild Shape")


def _slot_to_wild_shape(character, params, pools) -> str:
    _spend_slot(character, pools, str(params.get("slot", "")))
    _gain(character, WILD_SHAPE, 1)
    return _("You regain one use of Wild Shape")


def _wild_to_slot(character, params, pools) -> str:
    _spend(character, WILD_SHAPE, 1)
    _add_created_slot(character, 1)
    return _("You create a level 1 spell slot until your next long rest")


def _nature_magician(character, params, pools) -> str:
    uses = _int(params, "uses", 1)
    if not 1 <= uses <= min(4, left(character, WILD_SHAPE)):
        raise ValueError("invalid number of uses")
    _spend(character, WILD_SHAPE, uses)
    _add_created_slot(character, 2 * uses)
    return _("You create a level %(level)d spell slot until your next long rest") % {
        "level": 2 * uses
    }


_EFFECTS = {
    "restoration": _restoration,
    "uncanny": _uncanny,
    "perfect_focus": _perfect_focus,
    "persistent_rage": _persistent_rage,
    "superior_inspiration": _superior_inspiration,
    "slot_to_bardic": _slot_to_bardic,
    "magical_cunning": _magical_cunning,
    "slot_to_points": _slot_to_points,
    "create_slot": _create_slot,
    "evergreen": _evergreen,
    "slot_to_wild_shape": _slot_to_wild_shape,
    "wild_to_slot": _wild_to_slot,
    "nature_magician": _nature_magician,
}

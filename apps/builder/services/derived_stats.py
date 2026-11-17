"""Derived statistics: everything the SRD step 5 says to "write in the numbers".

Computed from a character's persisted rows, never stored (a stored AC goes stale the moment an
item or feature changes; a computed one cannot). The wizard's Review step and, later, the
character sheet both read this. All formulas are the SRD's: see
`docs/character_creation_plan.md` section 7.
"""

from dataclasses import dataclass, field
from types import SimpleNamespace

from apps.characters import conditions, custom_effects
from apps.characters.models import Character, CharacterChoice
from apps.rules.models import ClassLevel, Skill

from .. import tables
from ..class_spec import CLASS_SPEC
from ..progression_spec import SUBCLASS_CASTING
from ..resolvers.proficiency import WeaponProficiency
from . import wild_shape

_ARMOR_CATEGORY = {"la": "light", "ma": "medium", "ha": "heavy"}
_LEVEL_MULTIPLIER = {"proficient": 1, "expertise": 2}
#: Skills a Thaumaturge (Cleric) / Magician (Druid) adds their Wisdom modifier to, by order option.
_ORDER_SKILL_BONUS = {
    order.feature: order.wisdom_bonus_skills
    for spec in CLASS_SPEC.values()
    for order in spec.orders
    if order.wisdom_bonus_skills
}


@dataclass
class Derived:
    level: int
    proficiency_bonus: int
    abilities: dict[str, dict]
    saving_throws: dict[str, dict]
    skills: dict[str, dict]
    passive_perception: int
    initiative: int
    speed: int
    armor_class: dict
    hit_dice: dict[str, dict]
    attacks: list[dict]
    spellcasting: list[dict]
    warnings: list[str] = field(default_factory=list)
    #: The same warnings, by the equipment id of the worn piece they belong to.
    item_warnings: dict[str, list[str]] = field(default_factory=dict)
    #: The Beast (`rules.Creature`) a Druid is shape-shifted into, whose statistics replaced the
    #: Armor Class, Speed, Strength, Dexterity and Constitution here (`wild_shape.py`); else None.
    form: object | None = None


#: What a custom armor kind counts as (the `rules.EquipmentType` ids the AC formula knows).
_CUSTOM_ARMOR_TYPE = {"light": "la", "medium": "ma", "heavy": "ha", "shield": tables.SHIELD_TYPE_ID}
_NO_MASTERIES = SimpleNamespace(all=lambda: [])


def _custom_piece(item) -> SimpleNamespace:
    """A worn custom armor/shield, shaped like the `Equipment` fields the AC code reads."""
    return SimpleNamespace(
        id=f"custom:{item.pk}",
        name_en=item.name,
        custom_name=item.name,
        type_id=_CUSTOM_ARMOR_TYPE[item.armor_kind],
        ac=item.ac,
        strength_requirement=item.strength_requirement,
        stealth_disadvantage=item.stealth_disadvantage,
    )


def _custom_weapon(item) -> SimpleNamespace:
    """A custom weapon, shaped like the `Equipment` fields the attack code reads."""
    props = [pid for pid, on in (("f", item.finesse), ("2h", item.two_handed)) if on]
    return SimpleNamespace(
        id=f"custom:{item.pk}",
        custom_name=item.name,
        type_id="r" if item.ranged else "m",
        weapon_category=item.weapon_category,
        damage_dice=item.damage_dice,
        damage_type=item.damage_type,
        versatile_damage_dice=item.versatile_damage_dice,
        properties=SimpleNamespace(all=lambda: [SimpleNamespace(id=pid) for pid in props]),
        masteries=_NO_MASTERIES,
    )


def weapon_proficiency(names) -> WeaponProficiency:
    """Rebuild the weapon proficiency from stored names: `simple`, `martial`, `martial:f,l`
    (a filtered grant), `improvised`."""
    proficiency = WeaponProficiency()
    for name in names:
        category, _sep, properties = name.partition(":")
        if properties:
            proficiency.filtered.append((category, set(properties.split(","))))
        elif category in ("simple", "martial"):
            proficiency.categories.add(category)
        else:
            proficiency.named.add(category)
    return proficiency


#: Unarmored Movement: Speed bonus by Monk level (needs no armor and no shield).
_UNARMORED_MOVEMENT = ((18, 30), (14, 25), (10, 20), (6, 15), (2, 10))


def _armor_class(mods, worn_armor, worn_shield, has_feature, feats=frozenset(), names=frozenset()):
    dex = mods["dex"]
    if worn_armor:
        cap = tables.ARMOR_DEX_CAP[worn_armor.type_id]
        if cap == 2 and "Medium Armor Master" in feats:
            cap = 3
        # Heavy armor (cap 0) ignores Dexterity altogether - a negative modifier included.
        bonus = 0 if cap == 0 else (dex if cap is None else min(dex, cap))
        base = (worn_armor.ac or 10) + bonus
        formula = f"{worn_armor.name_en}"
    else:
        base, formula = 10 + dex, "unarmored"
    if worn_shield:
        base += worn_shield.ac or 2
    if worn_armor and "Defense" in feats:  # the Fighting Style: +1 in any armor
        base += 1
    best = {
        "value": base,
        "formula": formula,
        "shield": bool(worn_shield),
        "armor_id": worn_armor.id if worn_armor else None,
        # A custom armor has no catalog row to look the name up in.
        "armor_name": getattr(worn_armor, "custom_name", ""),
    }
    if not worn_armor:
        if "Draconic Resilience" in names:  # Draconic Sorcerer: 10 + Dex + Cha, shield allowed
            value = 10 + dex + mods["cha"] + ((worn_shield.ac or 2) if worn_shield else 0)
            if value > best["value"]:
                best = {
                    "value": value,
                    "formula": "draconic resilience",
                    "shield": bool(worn_shield),
                    "armor_id": None,
                    "armor_name": "",
                }
        for class_id, spec in CLASS_SPEC.items():
            if not spec.unarmored_defense or not has_feature(class_id):
                continue
            ability, shield_allowed = spec.unarmored_defense
            if worn_shield and not shield_allowed:
                continue  # Monk: no armor *and* no shield
            value = 10 + dex + mods[ability] + ((worn_shield.ac or 2) if worn_shield else 0)
            # One calculation at a time (SRD multiclass rule): keep the best.
            if value > best["value"]:
                best = {
                    "value": value,
                    "formula": f"unarmored defense ({ability})",
                    "shield": bool(worn_shield),
                    "armor_id": None,
                    "armor_name": "",
                }
    return best


def compute(character: Character) -> Derived:
    classes = list(character.classes.select_related("klass", "subclass"))
    level = sum(c.level for c in classes) or 1
    pb = tables.proficiency_bonus(level)
    scores = {
        "str": character.strength,
        "dex": character.dexterity,
        "con": character.constitution,
        "int": character.intelligence,
        "wis": character.wisdom,
        "cha": character.charisma,
    }
    # What the player's own features and worn items do (`custom_effects`): bonuses add up, a flag
    # (proficiency, expertise) is there or not.
    custom = custom_effects.collect(character)

    def bonus(target: str) -> int:
        return sum(e["value"] for e, _owner in custom if e["target"] == target)

    def flagged(target: str) -> bool:
        return any(e["target"] == target for e, _owner in custom)

    for ability in tables.ABILITIES:
        scores[ability] += bonus(f"ability:{ability}")
        scores[ability] = max(scores[ability], bonus(f"ability_min:{ability}"))
    # Drained scores (until a Long Rest) count as lowered everywhere they are used.
    for ability, lost in (character.ability_reductions or {}).items():
        if ability in scores:
            scores[ability] = max(0, scores[ability] - int(lost))
    # Wild Shape: the Beast's Strength, Dexterity and Constitution replace the Druid's
    # (Intelligence, Wisdom and Charisma stay).
    form = wild_shape.active_form(character)
    if form:
        for ability in ("str", "dex", "con"):
            scores[ability] = form.abilities[ability]["score"]
    mods = {a: tables.ability_modifier(s) for a, s in scores.items()}
    prof_rows = list(character.proficiencies.all())
    held = {(p.category, p.name): p.level for p in prof_rows}
    choices = {c.key: c.value for c in CharacterChoice.objects.filter(character=character)}
    warnings: list[str] = []
    feature_names = set(character.features.values_list("feature__name_en", flat=True))
    feat_names = {f.feat.name_en for f in character.feats.select_related("feat")}

    saves = {}
    for a in tables.ABILITIES:
        proficient = ("saving_throw", a) in held or flagged(f"prof_save:{a}")
        saves[a] = {
            "modifier": mods[a]
            + (pb if proficient else 0)
            + bonus(f"save:{a}")
            + bonus("save_all"),
            "proficient": proficient,
        }

    order_feature = next(
        (o for o in _ORDER_SKILL_BONUS if _order_slug(o) == choices.get("class.order")), None
    )
    bonus_skills = _ORDER_SKILL_BONUS.get(order_feature, ())
    skills = {}
    for skill in Skill.objects.select_related("ability").order_by("name"):
        state = held.get(("skill", skill.id))
        if flagged(f"expert_skill:{skill.id}"):
            state = "expertise"
        elif not state and flagged(f"prof_skill:{skill.id}"):
            state = "proficient"
        extra = max(1, mods["wis"]) if skill.id in bonus_skills and skill.ability_id == "int" else 0
        jack = pb // 2 if not state and "Jack of All Trades" in feature_names else 0
        skills[skill.id] = {
            "ability": skill.ability_id,
            "state": state or "none",
            "modifier": mods[skill.ability_id]
            + pb * _LEVEL_MULTIPLIER.get(state, 0)
            + extra
            + jack
            + bonus(f"skill:{skill.id}")
            + bonus("skill_all"),
            "bonus": extra,
        }

    if form:
        # Own proficiencies stay with the Druid's Proficiency Bonus; a higher bonus in the stat
        # block wins.
        by_name = {s.name_en: s.id for s in Skill.objects.all()}
        for name, beast_bonus in (form.skills or {}).items():
            entry = skills.get(by_name.get(name))
            if entry and beast_bonus > entry["modifier"]:
                entry["modifier"] = beast_bonus
    items = list(
        character.inventory_items.select_related("equipment__type").prefetch_related(
            "equipment__properties"
        )
    )
    custom_items = list(character.custom_items.all())
    worn = [i.equipment for i in items if i.equipped] + [
        _custom_piece(i)
        for i in custom_items
        if i.equipped and i.section == "armor" and i.armor_kind and i.ac
    ]
    worn_armor = next((e for e in worn if e.type_id in _ARMOR_CATEGORY), None)
    worn_shield = next((e for e in worn if e.type_id == tables.SHIELD_TYPE_ID), None)

    def has_feature(class_id: str) -> bool:
        return "Unarmored Defense" in feature_names and any(c.klass_id == class_id for c in classes)

    ac = _armor_class(mods, worn_armor, worn_shield, has_feature, feat_names, feature_names)
    ac["value"] += bonus("ac")
    if form:
        ac = {
            **ac,
            "value": form.ac,
            "formula": "beast form",
            "shield": False,
            "armor_id": None,
            "armor_name": "",
        }

    item_warnings: dict[str, list[str]] = {}

    def warn(piece, code: str) -> None:
        warnings.append(code)
        item_warnings.setdefault(piece.id, []).append(code)

    speed = _speed(character, choices) + bonus("speed")
    heavy = bool(worn_armor and worn_armor.type_id == "ha")
    if "Speedy" in feat_names:
        speed += 10
    if "Boon of Speed" in feat_names:
        speed += 30
    for c in classes:
        if c.klass_id == "barbarian" and c.level >= 5 and "Fast Movement" in feature_names:
            speed += 0 if heavy else 10
        elif c.klass_id == "ranger" and c.level >= 6 and "Roving" in feature_names:
            speed += 0 if heavy else 10
        elif c.klass_id == "monk" and "Unarmored Movement" in feature_names:
            if not (worn_armor or worn_shield):
                speed += next((v for lvl, v in _UNARMORED_MOVEMENT if c.level >= lvl), 0)
    for piece in (worn_armor, worn_shield):
        if piece is None:
            continue
        category = _ARMOR_CATEGORY.get(piece.type_id, "shield")
        if ("armor", category) not in held:
            # d20 disadvantage on Str/Dex, no spells
            warn(piece, f"not_proficient:{category}")
    if (
        worn_armor
        and worn_armor.strength_requirement
        and scores["str"] < worn_armor.strength_requirement
    ):
        speed -= 10
        warn(worn_armor, "strength_requirement")
    if worn_armor and worn_armor.stealth_disadvantage:
        warn(worn_armor, "stealth_disadvantage")

    weapons = weapon_proficiency(n for c, n in held if c == "weapon")
    # Versatile: the two-handed damage needs both hands, so no shield and no other weapon wielded.
    wielded = [i.equipment for i in items if i.equipped and i.equipment.type_id in ("m", "r")] + [
        _custom_weapon(i) for i in custom_items if i.equipped and i.section == "weapons"
    ]
    candidates = [(i.equipment, i.equipment_id) for i in items] + [
        (_custom_weapon(i), f"custom:{i.pk}")
        for i in custom_items
        if i.section == "weapons" and i.damage_dice
    ]
    # A weapon's own bonuses (a +1 sword) count whether or not it is wielded right now.
    own = {
        f"custom:{i.pk}": i.effects for i in custom_items if i.section == "weapons" and i.effects
    }

    def weapon_bonus(target: str, equipment_id) -> int:
        return sum(e["value"] for e in own.get(equipment_id, []) if e["target"] == target)

    attacks = []
    for eq, equipment_id in candidates:
        if eq.weapon_category not in ("simple", "martial") or eq.type_id not in ("m", "r"):
            continue
        props = {p.id for p in eq.properties.all()}
        finesse = "f" in props
        if eq.type_id == "r":
            ability = "dex"
        elif finesse:
            ability = "dex" if mods["dex"] > mods["str"] else "str"
        else:
            ability = "str"
        proficient = weapons.covers(eq)
        hit_extra = (2 if "Archery" in feat_names and eq.type_id == "r" else 0) + bonus("attack")
        hit_extra += weapon_bonus("weapon_attack", equipment_id)
        damage_extra = bonus("damage") + weapon_bonus("weapon_damage", equipment_id)
        # Dueling: a melee weapon held in one hand (not Two-Handed; the other hand free).
        dueling = "Dueling" in feat_names and eq.type_id == "m" and "2h" not in props
        dmg = mods[ability] + (2 if dueling else 0) + damage_extra
        # Two hands on a Versatile weapon: the bigger die, and no Dueling (that is one hand).
        two_hand_dmg = mods[ability] + damage_extra
        others = [w for w in wielded if w.id != equipment_id]
        attacks.append(
            {
                "equipment_id": equipment_id,
                "custom_name": getattr(eq, "custom_name", ""),
                "ability": ability,
                "proficient": proficient,
                "attack_bonus": mods[ability] + (pb if proficient else 0) + hit_extra,
                "damage": f"{eq.damage_dice}{dmg:+d}" if dmg else eq.damage_dice,
                "damage_type": eq.damage_type,
                "damage_two_handed": (
                    f"{eq.versatile_damage_dice}{two_hand_dmg:+d}"
                    if two_hand_dmg
                    else eq.versatile_damage_dice
                )
                if eq.versatile_damage_dice
                else "",
                "two_hands_free": not worn_shield and not others,
                "masteries": [m.id for m in eq.masteries.all()]
                if equipment_id in (choices.get("class.weapon_mastery") or [])
                else [],
            }
        )

    hit_dice: dict[str, dict] = {}
    for c in classes:
        entry = hit_dice.setdefault(c.klass.hit_die, {"total": 0, "spent": 0})
        entry["total"] += c.level
        entry["spent"] += c.hit_dice_spent

    initiative_bonus = bonus("initiative")
    if "Alert" in feat_names:
        initiative_bonus += pb
    elif "Jack of All Trades" in feature_names:
        initiative_bonus += pb // 2

    # Conditions: Exhaustion lowers every D20 Test (not a spell's save DC) and the Speed; some
    # conditions hold the Speed at 0. Ability checks are rolled from the plain modifiers, so the
    # Exhaustion penalty only shows where a total is displayed (saves, skills, attacks, initiative).
    if form:
        speed = form.speed.get("walk", 0)
        attacks = []  # the Beast's own actions are on its stat block
    fx = conditions.effects(character)
    if fx.d20_penalty:
        for entry in (*saves.values(), *skills.values()):
            entry["modifier"] -= fx.d20_penalty
        for attack in attacks:
            attack["attack_bonus"] -= fx.d20_penalty
    speed = 0 if fx.speed_zero else max(0, speed - fx.speed_penalty)
    spellcasting = _spellcasting(classes, choices, mods, pb)
    for entry in spellcasting:
        entry["save_dc"] += bonus("spell_dc")
        entry["attack_bonus"] += bonus("spell_attack")
    if fx.d20_penalty:
        for entry in spellcasting:
            if "attack_bonus" in entry:
                entry["attack_bonus"] -= fx.d20_penalty

    return Derived(
        level=level,
        proficiency_bonus=pb,
        abilities={a: {"score": scores[a], "modifier": mods[a]} for a in tables.ABILITIES},
        saving_throws=saves,
        skills=skills,
        passive_perception=10 + skills["perception"]["modifier"] + bonus("passive_perception"),
        initiative=mods["dex"] + initiative_bonus - fx.d20_penalty,
        speed=speed,
        armor_class=ac,
        hit_dice=hit_dice,
        attacks=attacks,
        spellcasting=spellcasting,
        warnings=warnings,
        item_warnings=item_warnings,
        form=form,
    )


def _order_slug(feature: str) -> str:
    return feature.lower().replace(" ", "-")


def _speed(character: Character, choices: dict) -> int:
    species = character.species
    if species is None:
        return 30
    lineage = next(
        (lin for lin in species.lineages if lin["key"] == choices.get("species.lineage")), None
    )
    return lineage["speed"] if lineage and "speed" in lineage else species.speed


def _spellcasting(classes, choices, mods, pb) -> list[dict]:
    """One entry per source that casts: each class with a spellcasting ability, plus species and
    feat spells (which use the ability the player chose)."""
    result = []
    for c in classes:
        third = (
            SUBCLASS_CASTING.get((c.klass_id, c.subclass.name_en))
            if c.subclass and c.level >= 3
            else None
        )
        ability = c.klass.spellcasting_ability_id or (third.ability if third else None)
        if not ability:
            continue
        row = ClassLevel.objects.filter(klass=c.klass, level=c.level).first()
        if third:  # Eldritch Knight / Arcane Trickster: the subclass's own tables
            slots, cantrips = list(third.slots[c.level - 1]), third.cantrips[c.level - 1]
            prepared, pact = third.prepared[c.level - 1], None
        else:
            slots = list(row.spell_slots) if row and row.spell_slots else []
            cantrips = row.cantrips_known if row else None
            prepared = row.spells_known_or_prepared if row else None
            pact = _pact(row)
        result.append(
            {
                "source": f"class:{c.klass_id}",
                "ability": ability,
                "save_dc": 8 + mods[ability] + pb,
                "attack_bonus": mods[ability] + pb,
                "slots": slots,
                "pact": pact,
                "cantrips": cantrips,
                "prepared": prepared,
            }
        )
    feat_sources = [("species.spell_ability", "species"), ("background.feat", "feat")]
    feat_sources += [(key, "feat") for key in choices if key.startswith("levelup.feat.")]
    for key, source in feat_sources:
        value = choices.get(key)
        ability = value.get("spell_ability") if isinstance(value, dict) else value
        if ability in mods:
            result.append(
                {
                    "source": source,
                    "ability": ability,
                    "save_dc": 8 + mods[ability] + pb,
                    "attack_bonus": mods[ability] + pb,
                    "slots": [],
                    "pact": None,
                    "cantrips": None,
                    "prepared": None,
                }
            )
    return result


def _pact(row) -> dict | None:
    """Warlock Pact Magic: `{"slots": n, "level": slot level}`; `None` for everyone else."""
    if row and "Spell Slots" in row.columns:
        return {
            "slots": int(row.columns["Spell Slots"]),
            "level": int(row.columns.get("Slot Level", 1)),
        }
    return None

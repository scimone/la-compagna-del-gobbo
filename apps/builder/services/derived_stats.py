"""Derived statistics: everything the SRD step 5 says to "write in the numbers".

Computed from a character's persisted rows, never stored (a stored AC goes stale the moment an
item or feature changes; a computed one cannot). The wizard's Review step and, later, the
character sheet both read this. All formulas are the SRD's: see
`docs/character_creation_plan.md` section 7.
"""

from dataclasses import dataclass, field

from apps.characters.models import Character, CharacterChoice
from apps.rules.models import ClassLevel, Skill

from .. import tables
from ..class_spec import CLASS_SPEC
from ..resolvers.proficiency import WeaponProficiency

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


def _weapon_proficiency(names) -> WeaponProficiency:
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


def _armor_class(mods, worn_armor, worn_shield, has_feature):
    dex = mods["dex"]
    if worn_armor:
        cap = tables.ARMOR_DEX_CAP[worn_armor.type_id]
        # Heavy armor (cap 0) ignores Dexterity altogether - a negative modifier included.
        bonus = 0 if cap == 0 else (dex if cap is None else min(dex, cap))
        base = (worn_armor.ac or 10) + bonus
        formula = f"{worn_armor.name_en}"
    else:
        base, formula = 10 + dex, "unarmored"
    if worn_shield:
        base += worn_shield.ac or 2
    best = {
        "value": base,
        "formula": formula,
        "shield": bool(worn_shield),
        "armor_id": worn_armor.id if worn_armor else None,
    }
    if not worn_armor:
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
                }
    return best


def compute(character: Character) -> Derived:
    classes = list(character.classes.select_related("klass"))
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
    mods = {a: tables.ability_modifier(s) for a, s in scores.items()}
    prof_rows = list(character.proficiencies.all())
    held = {(p.category, p.name): p.level for p in prof_rows}
    choices = {c.key: c.value for c in CharacterChoice.objects.filter(character=character)}
    warnings: list[str] = []

    saves = {
        a: {
            "modifier": mods[a] + (pb if ("saving_throw", a) in held else 0),
            "proficient": ("saving_throw", a) in held,
        }
        for a in tables.ABILITIES
    }

    order_feature = next(
        (o for o in _ORDER_SKILL_BONUS if _order_slug(o) == choices.get("class.order")), None
    )
    bonus_skills = _ORDER_SKILL_BONUS.get(order_feature, ())
    skills = {}
    for skill in Skill.objects.select_related("ability").order_by("name"):
        state = held.get(("skill", skill.id))
        extra = max(1, mods["wis"]) if skill.id in bonus_skills and skill.ability_id == "int" else 0
        skills[skill.id] = {
            "ability": skill.ability_id,
            "state": state or "none",
            "modifier": mods[skill.ability_id] + pb * _LEVEL_MULTIPLIER.get(state, 0) + extra,
            "bonus": extra,
        }

    items = list(
        character.inventory_items.select_related("equipment__type").prefetch_related(
            "equipment__properties"
        )
    )
    worn = [i.equipment for i in items if i.equipped]
    worn_armor = next((e for e in worn if e.type_id in _ARMOR_CATEGORY), None)
    worn_shield = next((e for e in worn if e.type_id == tables.SHIELD_TYPE_ID), None)
    feature_names = set(character.features.values_list("feature__name", flat=True))

    def has_feature(class_id: str) -> bool:
        return "Unarmored Defense" in feature_names and any(c.klass_id == class_id for c in classes)

    ac = _armor_class(mods, worn_armor, worn_shield, has_feature)

    speed = _speed(character, choices)
    for piece in (worn_armor, worn_shield):
        if piece is None:
            continue
        category = _ARMOR_CATEGORY.get(piece.type_id, "shield")
        if ("armor", category) not in held:
            warnings.append(f"not_proficient:{category}")  # d20 disadvantage on Str/Dex, no spells
    if (
        worn_armor
        and worn_armor.strength_requirement
        and scores["str"] < worn_armor.strength_requirement
    ):
        speed -= 10
        warnings.append("strength_requirement")
    if worn_armor and worn_armor.stealth_disadvantage:
        warnings.append("stealth_disadvantage")

    weapons = _weapon_proficiency(n for c, n in held if c == "weapon")
    attacks = []
    for item in items:
        eq = item.equipment
        if eq.weapon_category not in ("simple", "martial") or eq.type_id not in ("m", "r"):
            continue
        finesse = "f" in {p.id for p in eq.properties.all()}
        if eq.type_id == "r":
            ability = "dex"
        elif finesse:
            ability = "dex" if mods["dex"] > mods["str"] else "str"
        else:
            ability = "str"
        proficient = weapons.covers(eq)
        attacks.append(
            {
                "equipment_id": eq.id,
                "ability": ability,
                "proficient": proficient,
                "attack_bonus": mods[ability] + (pb if proficient else 0),
                "damage": f"{eq.damage_dice}{mods[ability]:+d}"
                if mods[ability]
                else eq.damage_dice,
                "damage_type": eq.damage_type,
                "masteries": [m.id for m in eq.masteries.all()]
                if eq.id in (choices.get("class.weapon_mastery") or [])
                else [],
            }
        )

    hit_dice: dict[str, dict] = {}
    for c in classes:
        entry = hit_dice.setdefault(c.klass.hit_die, {"total": 0, "spent": 0})
        entry["total"] += c.level
        entry["spent"] += c.hit_dice_spent

    return Derived(
        level=level,
        proficiency_bonus=pb,
        abilities={a: {"score": scores[a], "modifier": mods[a]} for a in tables.ABILITIES},
        saving_throws=saves,
        skills=skills,
        passive_perception=10 + skills["perception"]["modifier"],
        initiative=mods["dex"],
        speed=speed,
        armor_class=ac,
        hit_dice=hit_dice,
        attacks=attacks,
        spellcasting=_spellcasting(classes, choices, mods, pb),
        warnings=warnings,
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
        ability = c.klass.spellcasting_ability_id
        if not ability:
            continue
        row = ClassLevel.objects.filter(klass=c.klass, level=c.level).first()
        result.append(
            {
                "source": f"class:{c.klass_id}",
                "ability": ability,
                "save_dc": 8 + mods[ability] + pb,
                "attack_bonus": mods[ability] + pb,
                "slots": list(row.spell_slots) if row and row.spell_slots else [],
                "pact": _pact(row),
                "cantrips": row.cantrips_known if row else None,
                "prepared": row.spells_known_or_prepared if row else None,
            }
        )
    for key, source in (("species.spell_ability", "species"), ("background.feat", "feat")):
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

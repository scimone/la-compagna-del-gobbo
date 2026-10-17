"""Spell lists and the source's `additionalSpells` grants (species, feats)."""

from dataclasses import dataclass, field

from django.utils.text import slugify

from apps.rules.models import Class, ClassLevel, Spell

_CASTER_LEVEL_HIGHEST_SLOT = "Slot Level"  # `ClassLevel.columns` header for Pact Magic


def spell_id(ref: str) -> str:
    """`"dancing lights|xphb#c"` -> `"dancing-lights"` (the id `Spell` rows use)."""
    return slugify(ref.split("|")[0].split("#")[0])


def class_spell_list(class_name: str, level: int):
    """Spells of exactly `level` on `class_name`'s spell list (`Spell.classes` names a class)."""
    # The source writes it both ways ("Cleric", "cleric" in Blessed Warrior).
    class_name = class_name[:1].upper() + class_name[1:]
    return Spell.objects.filter(level=level, classes__contains=[class_name]).order_by("name")


#: A `school=` code of a `{"choose": ...}` filter -> `Spell.school`.
SCHOOL_CODES = {
    "A": "Abjuration",
    "C": "Conjuration",
    "D": "Divination",
    "E": "Enchantment",
    "V": "Evocation",
    "I": "Illusion",
    "N": "Necromancy",
    "T": "Transmutation",
}


def spell_pool(class_name: str, level: int, schools: tuple[str, ...] = (), ritual: bool = False):
    """The spells a pick can take: of exactly `level`, from `class_name`'s list when the filter
    names a class (otherwise any spell, e.g. Fey-Touched's "level 1, Divination or Enchantment"),
    narrowed to `schools` (full names) when it names some, and to ritual spells when `ritual`."""
    pool = class_spell_list(class_name, level) if class_name else Spell.objects.filter(level=level)
    if schools:
        pool = pool.filter(school__in=schools)
    if ritual:
        pool = pool.filter(ritual=True)
    return pool.order_by("name")


def max_spell_level(klass: Class, class_level: int) -> int:
    """Highest spell level the class can cast at `class_level`: the highest slot with any slots
    (full/half casters) or the Pact Magic slot level (Warlock). 0 for a non-caster."""
    row = ClassLevel.objects.filter(klass=klass, level=class_level).first()
    if not row:
        return 0
    if row.spell_slots:
        return max((i + 1 for i, n in enumerate(row.spell_slots) if n), default=0)
    return int(row.columns.get(_CASTER_LEVEL_HIGHEST_SLOT, 0) or 0)


def parse_choose(expression: str) -> tuple[int | None, str | None]:
    """`"level=0|class=Cleric"` -> `(0, "Cleric")` (the source's spell-filter mini-language)."""
    parts = dict(p.split("=", 1) for p in expression.split("|") if "=" in p)
    level = int(parts["level"]) if "level" in parts else None
    return level, parts.get("class")


def parse_ritual(expression: str) -> bool:
    """`"level=1|components & miscellaneous=ritual"` (Ritual Caster, Pact of the Tome)."""
    return "components & miscellaneous=ritual" in expression


def parse_schools(expression: str) -> tuple[str, ...]:
    """`"level=1|school=E;D"` -> `("Enchantment", "Divination")`; empty when no school is named."""
    parts = dict(p.split("=", 1) for p in expression.split("|") if "=" in p)
    codes = parts.get("school", "").split(";")
    return tuple(SCHOOL_CODES[c] for c in codes if c in SCHOOL_CODES)


@dataclass
class SpellPick:
    """A spell the player must choose: `count` spells of `level` from `class_name`'s list."""

    key: str
    level: int
    class_name: str
    count: int = 1
    schools: tuple[str, ...] = ()
    ritual: bool = False


@dataclass
class SpellGrant:
    """What one `additionalSpells` entry gives at a given character level."""

    fixed: list[str] = field(default_factory=list)  # spell ids known/prepared outright
    free_fixed: list[str] = field(default_factory=list)  # ...of which cast once per long rest
    at_will: list[str] = field(default_factory=list)  # ...of which cast without a slot, always
    picks: list[SpellPick] = field(default_factory=list)
    ability: str | None = None  # a fixed casting ability
    ability_options: list[str] = field(default_factory=list)  # ...or one to choose from


def _level_keyed(block, character_level: int):
    """`known`/`innate` blocks are keyed by the character level they unlock at (`"1"`, `"3"`, or
    `"_"` for "whenever the feat is taken"); yield the values that apply at `character_level`."""
    for key, value in (block or {}).items():
        if key == "_" or int(key) <= character_level:
            yield value


def spell_grant(entry: dict, character_level: int = 1) -> SpellGrant:
    """Resolve one `additionalSpells` entry (a species lineage's, or a feat variant's)."""
    grant = SpellGrant()
    ability = entry.get("ability")
    if isinstance(ability, dict):
        grant.ability_options = list(ability.get("choose", []))
    elif isinstance(ability, str):
        grant.ability = ability

    def take(items, pick_key, free=False, at_will=False):
        for item in items if isinstance(items, list) else items.get("_", []):
            if isinstance(item, str):
                grant.fixed.append(spell_id(item))
                if free:
                    grant.free_fixed.append(spell_id(item))
                if at_will:
                    grant.at_will.append(spell_id(item))
            elif isinstance(item, dict) and "choose" in item:
                level, class_name = parse_choose(item["choose"])
                grant.picks.append(
                    SpellPick(
                        pick_key,
                        level or 0,
                        class_name or "",
                        item.get("count", 1),
                        parse_schools(item["choose"]),
                        parse_ritual(item["choose"]),
                    )
                )

    for block in _level_keyed(entry.get("known"), character_level):
        take(block, "cantrips")
    # Ritual Caster: `prepared` spells, always prepared, more as the proficiency bonus grows.
    for block in _level_keyed(entry.get("prepared"), character_level):
        take(block, "rituals")
    for block in _level_keyed(entry.get("innate"), character_level):
        if isinstance(block, list):  # cast without a slot, as often as you like
            take(block, "spell", at_will=True)
            continue
        for kind, uses in (block or {}).items():
            if kind == "ritual":  # Pact of the Chain's Find Familiar, cast without a slot
                take(uses, "spell", at_will=True)
            elif kind == "daily":  # `{"1": [...]}`: once per long rest; a `_` block is a feat's
                for spells in uses.values():
                    take(spells, "spell", free=True)
    return grant


def option_spell_grant(option) -> SpellGrant | None:
    """What an optional feature (an Eldritch Invocation) gives in spells: Pact of the Chain's Find
    Familiar, Armor of Shadows' Mage Armor, Pact of the Tome's three cantrips and two rituals..."""
    return spell_grant(option.additional_spells[0]) if option.additional_spells else None


def option_spell_flags(grant: SpellGrant, spell: str) -> dict:
    """The `CharacterSpell` flags of one of `grant.fixed`: always prepared, and cast without a slot
    as often as you like (`at_will`) or once per long rest (a `daily` block)."""
    flags = {"prepared": True, "always_prepared": True}
    if spell in grant.at_will:
        flags |= {"free_cast": True, "free_cast_unlimited": True}
    elif spell in grant.free_fixed:
        flags["free_cast"] = True
    return flags


def option_source(option_id: str) -> str:
    return f"option:{option_id}"

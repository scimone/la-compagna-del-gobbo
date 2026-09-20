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
    return Spell.objects.filter(level=level, classes__contains=[class_name]).order_by("name")


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


@dataclass
class SpellPick:
    """A spell the player must choose: `count` spells of `level` from `class_name`'s list."""

    key: str
    level: int
    class_name: str
    count: int = 1


@dataclass
class SpellGrant:
    """What one `additionalSpells` entry gives at a given character level."""

    fixed: list[str] = field(default_factory=list)  # spell ids known/prepared outright
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

    def take(items, pick_key):
        for item in items if isinstance(items, list) else items.get("_", []):
            if isinstance(item, str):
                grant.fixed.append(spell_id(item))
            elif isinstance(item, dict) and "choose" in item:
                level, class_name = parse_choose(item["choose"])
                grant.picks.append(
                    SpellPick(pick_key, level or 0, class_name or "", item.get("count", 1))
                )

    for block in _level_keyed(entry.get("known"), character_level):
        take(block, "cantrips")
    for block in _level_keyed(entry.get("innate"), character_level):
        # `{"daily": {"1": [spell...]}}` - once-per-day spells; a `_` block is a feat's free spell.
        for uses in (block or {}).values():
            for spells in uses.values() if isinstance(uses, dict) else []:
                take(spells, "spell")
    return grant

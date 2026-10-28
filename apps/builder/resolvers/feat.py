"""A feat's own sub-choices and fixed grants, read from the structured data added to `Feat`
(`additional_spells`, `grants`) - Magic Initiate, Skilled, Musician, Crafter, Tavern Brawler.

A feat's picks are stored in one dict per source (`background.feat`, `species.feat`) keyed by the
`Pick.key` names below; `variant` (which Magic Initiate list) and `feat` (which feat, for the
Human's free Origin feat) are stored alongside them.
"""

from dataclasses import dataclass, field

from django.db.models import Q
from django.utils.text import slugify

from apps.rules.models import Equipment, Feat

from .proficiency import TOOL_KIND_TYPE
from .spell import SpellGrant, spell_grant


@dataclass
class Pick:
    """One decision a feat asks for. `kind`: `variant` | `ability` | `spell` | `skill` |
    `tool` | `skill_or_tool`. `options` is filled where the source enumerates them (variants,
    abilities, a fixed tool list); a spell pick is described by `level`/`class_name`, a tool pick
    without options by `tool_kinds` (`["anyMusicalInstrument"]`)."""

    key: str
    kind: str
    count: int = 1
    options: list[str] = field(default_factory=list)
    level: int = 0
    class_name: str = ""
    schools: tuple[str, ...] = ()
    ritual: bool = False
    tool_kinds: list[str] = field(default_factory=list)


def is_repeatable(feat: Feat) -> bool:
    return any(isinstance(e, dict) and e.get("name") == "Repeatable" for e in feat.entries_en)


def variants(feat: Feat) -> list[str]:
    """`["cleric", "druid", "wizard"]` for Magic Initiate; empty for a feat with one spell list
    (or none). A variant is the first word of an entry's name ("Cleric Spells")."""
    if len(feat.additional_spells) < 2:
        return []
    return [slugify(e["name"].split()[0]) for e in feat.additional_spells]


def _variant_entry(feat: Feat, variant: str) -> dict | None:
    if not feat.additional_spells:
        return None
    if len(feat.additional_spells) == 1:
        return feat.additional_spells[0]
    for entry in feat.additional_spells:
        if slugify(entry["name"].split()[0]) == variant:
            return entry
    return None


def spell_grant_for(feat: Feat, variant: str, character_level: int = 1) -> SpellGrant | None:
    entry = _variant_entry(feat, variant)
    return spell_grant(entry, character_level) if entry else None


def _tool_options_by_name(names: list[str]) -> list[str]:
    by_name = {e.name_en.lower(): e.id for e in Equipment.objects.all()}
    return [by_name[n] for n in names if n in by_name]


def picks(feat: Feat, variant: str = "", character_level: int = 1) -> list[Pick]:
    """Everything the player has to decide for `feat`, in the order a screen should ask."""
    result: list[Pick] = []
    if variants(feat):
        result.append(Pick("variant", "variant", options=variants(feat)))
    grant = (
        spell_grant_for(feat, variant, character_level) if (variant or not variants(feat)) else None
    )
    if grant:
        if grant.ability_options:
            result.append(Pick("spell_ability", "ability", options=grant.ability_options))
        for spell_pick in grant.picks:
            result.append(
                Pick(
                    spell_pick.key,
                    "spell",
                    count=spell_pick.count,
                    level=spell_pick.level,
                    class_name=spell_pick.class_name,
                    schools=spell_pick.schools,
                    ritual=spell_pick.ritual,
                )
            )
    for entry in feat.grants.get("toolProficiencies", []):
        choose = entry.get("choose")
        if choose:
            result.append(
                Pick(
                    "tools",
                    "tool",
                    count=choose.get("count", 1),
                    options=_tool_options_by_name(choose["from"]),
                )
            )
        for kind, count in entry.items():
            if kind in TOOL_KIND_TYPE:
                result.append(Pick("tools", "tool", count=count, tool_kinds=[kind]))
    for entry in feat.grants.get("skillToolLanguageProficiencies", []):
        for choose in entry.get("choose", []):
            result.append(Pick("proficiencies", "skill_or_tool", count=choose["count"]))
    return result


def fixed_weapon_grants(feat: Feat) -> list[str]:
    """Named weapon proficiencies the feat gives outright (Tavern Brawler: "improvised")."""
    return [
        k for e in feat.grants.get("weaponProficiencies", []) for k, v in e.items() if v is True
    ]


def origin_feats():
    return Feat.objects.filter(category="Origin").order_by("name")


def fighting_style_feats():
    return Feat.objects.filter(Q(category="Fighting Style")).order_by("name")


def apply_feat(
    grants, feat: Feat, chosen: dict, source: str, variant: str = "", character_level: int = 1
) -> None:
    """Add `feat` and the grants its picks (`chosen`) resolve to onto `grants`."""
    from .grants import SpellRow  # local: grants imports rules models only, avoid a cycle on reload

    grants.feats.append((feat, source))
    variant = variant or chosen.get("variant", "")
    spell = spell_grant_for(feat, variant, character_level)
    if spell:
        for spell_id in chosen.get("rituals", []):  # Ritual Caster: always prepared
            grants.add_spell(SpellRow(spell_id, f"feat:{feat.id}", always_prepared=True))
        for spell_id in [*spell.fixed, *chosen.get("cantrips", [])]:
            if spell_id in spell.free_fixed:  # Fey-/Shadow-Touched's Misty Step / Invisibility
                grants.add_spell(
                    SpellRow(spell_id, f"feat:{feat.id}", always_prepared=True, free_cast=True)
                )
            else:
                grants.add_spell(SpellRow(spell_id, f"feat:{feat.id}"))
        for spell_id in [chosen.get("spell")] if chosen.get("spell") else []:
            grants.add_spell(
                SpellRow(spell_id, f"feat:{feat.id}", always_prepared=True, free_cast=True)
            )
    for value in chosen.get("proficiencies", []):
        category, _, name = value.partition(":")
        grants.add_proficiency("skill" if category == "skill" else "tool", name)
    for tool_id in chosen.get("tools", []):
        grants.add_proficiency("tool", tool_id)
    for name in fixed_weapon_grants(feat):
        grants.add_proficiency("weapon", name)

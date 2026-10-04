"""What the chosen species (and its lineage/legacy/ancestry) gives a level-1 character."""

from apps.rules.models import Feat, Feature

from ..services.store import Draft
from . import feat as feat_resolver
from .grants import Grants, SpellRow
from .spell import SpellGrant, spell_grant


def chosen_lineage(draft: Draft) -> dict | None:
    if not draft.species:
        return None
    key = draft.get("species.lineage")
    return next((lin for lin in draft.species.lineages if lin["key"] == key), None)


def spell_entries(draft: Draft) -> list[dict]:
    """The species' unconditional spell grants plus the chosen lineage's own."""
    if not draft.species:
        return []
    lineage = chosen_lineage(draft)
    return [*draft.species.additional_spells, *(lineage["additional_spells"] if lineage else [])]


def spell_grants(draft: Draft) -> list[SpellGrant]:
    return [spell_grant(entry, draft.level) for entry in spell_entries(draft)]


def spell_ability_options(draft: Draft) -> list[str]:
    """Abilities to choose the species-spell casting ability from (empty when it is fixed or the
    species grants no spells)."""
    return next((g.ability_options for g in spell_grants(draft) if g.ability_options), [])


def spell_ability(draft: Draft) -> str | None:
    fixed = next((g.ability for g in spell_grants(draft) if g.ability), None)
    return fixed or draft.get("species.spell_ability")


def darkvision(draft: Draft) -> int:
    lineage = chosen_lineage(draft)
    if lineage and "darkvision" in lineage:
        return lineage["darkvision"]
    return draft.species.darkvision if draft.species else 0


def speed(draft: Draft) -> int:
    lineage = chosen_lineage(draft)
    if lineage and "speed" in lineage:
        return lineage["speed"]
    return draft.species.speed if draft.species else 30


def resistances(draft: Draft) -> list[str]:
    if not draft.species:
        return []
    lineage = chosen_lineage(draft)
    return [*draft.species.resistances, *(lineage["resistances"] if lineage else [])]


def size(draft: Draft) -> str:
    """`"S"` or `"M"`: the only size a species has, or the one the player picked."""
    if not draft.species:
        return ""
    sizes = draft.species.size
    return sizes[0] if len(sizes) == 1 else draft.get("species.size", "")


def species_features(draft: Draft) -> list[Feature]:
    """The species' traits, with the generic lineage trait ("Elven Lineage", listing every
    lineage in a table) swapped for the chosen lineage's own ("Elven Lineage (Wood Elf)")."""
    rows = list(draft.species.feature_rows.order_by("pk"))
    lineage = chosen_lineage(draft)
    if lineage is None:
        return [f for f in rows if not f.choice_option]
    chosen = f"{lineage['replaces']} ({lineage['label']})"
    own = next((f for f in rows if f.name_en == chosen), None)
    if own is None:
        return rows
    generic = lineage["replaces"]
    others = [f for f in rows if f.name_en != generic and not f.name_en.startswith(f"{generic} (")]
    return [*others, own]


def species_grants(draft: Draft, grants: Grants) -> None:
    species = draft.species
    if species is None:
        return
    grants.features.extend(species_features(draft))
    if (feet := darkvision(draft)) > 0:
        grants.senses.append(("darkvision", feet, "species"))

    source = f"species:{species.id}"
    chosen_spells = draft.get("species.cantrip", [])
    for spell in spell_grants(draft):
        for spell_id in spell.fixed:
            # Cantrips known at level 1 are always available; leveled ones are "always prepared".
            grants.add_spell(SpellRow(spell_id, source, always_prepared=True))
        for _pick in spell.picks:
            for spell_id in chosen_spells:
                grants.add_spell(SpellRow(spell_id, source, always_prepared=True))

    if skill_id := draft.get("species.skill"):
        grants.add_proficiency("skill", skill_id)
    if extra := draft.get("species.feat"):
        if extra.get("feat"):
            feat_resolver.apply_feat(grants, Feat.objects.get(id=extra["feat"]), extra, "species")

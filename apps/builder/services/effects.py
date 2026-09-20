"""Recompute a draft character's rows from its choices.

`apply()` is the only thing that writes proficiencies, features, feats, spells, inventory,
languages, senses, resources and ability scores while a character is being created. It deletes
every one of those rows and rebuilds them from the choices, so it is idempotent, and going back to
change the background can never leave a stale grant behind. The manual overrides
(`manual.abilities`, `manual.skills`) are applied last: they win over class, species and
background, and survive every recompute.

Only drafts are recomputed: once a character is complete its rows are its own to edit.
"""

from django.db import transaction

from apps.characters.models import (
    Character,
    CharacterAbilityScoreIncrease,
    CharacterCurrency,
    CharacterFeat,
    CharacterFeature,
    CharacterInventoryItem,
    CharacterLanguage,
    CharacterOptionalFeature,
    CharacterProficiency,
    CharacterResource,
    CharacterSense,
    CharacterSpell,
)
from apps.rules.models import Language, Sense, Skill

from .. import tables
from ..resolvers import abilities as ability_resolver
from ..resolvers import equipment as equipment_resolver
from ..resolvers import species as species_resolver
from ..resolvers.background import background_grants
from ..resolvers.class_ import class_grants
from ..resolvers.grants import Grants
from ..resolvers.species import species_grants
from .store import Draft

_ARMOR_TYPE_CATEGORY = {"la": "light", "ma": "medium", "ha": "heavy", "s": "shield"}
_GENERATED = (
    CharacterProficiency,
    CharacterFeature,
    CharacterFeat,
    CharacterOptionalFeature,
    CharacterLanguage,
    CharacterSense,
    CharacterSpell,
    CharacterResource,
    CharacterAbilityScoreIncrease,
)


def compute_grants(draft: Draft, *, manual: bool = True) -> Grants:
    """Everything the draft's choices grant, manual skill overrides included unless
    `manual=False` (what the rules alone give). No writes."""
    grants = Grants()
    grants.add_language(tables.COMMON_LANGUAGE_ID)
    for language_id in draft.get("languages", []):
        grants.add_language(language_id)
    class_grants(draft, grants)
    species_grants(draft, grants)
    background_grants(draft, grants)
    for skill_id, state in (draft.get("manual.skills") or {}).items() if manual else ():
        if state == "none":
            grants.proficiencies.pop(("skill", skill_id), None)
        else:
            grants.proficiencies[("skill", skill_id)] = state
    return grants


def _equipped_armor(items, grants: Grants) -> set[int]:
    """Indexes of the armor pieces to wear: the best-AC body armor and the shield, if proficient."""
    worn: set[int] = set()
    best: tuple[int, int] | None = None
    for index, grant in enumerate(items):
        category = _ARMOR_TYPE_CATEGORY.get(grant.equipment.type_id)
        if category is None or ("armor", category) not in grants.proficiencies:
            continue
        if category == "shield":
            worn.add(index)
        elif best is None or (grant.equipment.ac or 0) > best[0]:
            best = (grant.equipment.ac or 0, index)
    if best:
        worn.add(best[1])
    return worn


@transaction.atomic
def apply(character: Character) -> None:
    if character.status != Character.STATUS_DRAFT:
        return
    from . import prune  # local: prune -> origins/class_choices -> effects

    prune.run(character)
    draft = Draft(character)
    grants = compute_grants(draft)
    items, gold, _problems = equipment_resolver.resolve(draft)

    for model in _GENERATED:
        model.objects.filter(character=character).delete()
    CharacterInventoryItem.objects.filter(character=character).delete()

    skills = {s.id: s for s in Skill.objects.all()}
    CharacterProficiency.objects.bulk_create(
        CharacterProficiency(
            character=character,
            category=category,
            name=name,
            skill=skills.get(name) if category == "skill" else None,
            level=level,
        )
        for (category, name), level in grants.proficiencies.items()
    )
    CharacterFeature.objects.bulk_create(
        CharacterFeature(character=character, feature=f, granted_at_level=1)
        for f in {f.pk: f for f in grants.features}.values()
    )
    CharacterFeat.objects.bulk_create(
        CharacterFeat(character=character, feat=feat, granted_at_level=1, source=source)
        for feat, source in grants.feats
    )
    CharacterOptionalFeature.objects.bulk_create(
        CharacterOptionalFeature(character=character, optional_feature=o, granted_at_level=1)
        for o in grants.optional_features
    )
    valid_languages = set(
        Language.objects.filter(id__in=grants.languages).values_list("id", flat=True)
    )
    CharacterLanguage.objects.bulk_create(
        CharacterLanguage(character=character, language_id=lang)
        for lang in grants.languages
        if lang in valid_languages
    )
    valid_senses = set(Sense.objects.values_list("id", flat=True))
    CharacterSense.objects.bulk_create(
        CharacterSense(character=character, sense_id=sense, range_feet=feet, source=source)
        for sense, feet, source in grants.senses
        if sense in valid_senses
    )
    CharacterSpell.objects.bulk_create(
        CharacterSpell(
            character=character,
            spell_id=row.spell_id,
            klass_id=row.klass_id,
            prepared=row.prepared,
            always_prepared=row.always_prepared,
            in_spellbook=row.in_spellbook,
            source=row.source,
        )
        for row in grants.spells.values()
    )
    CharacterResource.objects.bulk_create(
        CharacterResource(
            character=character, name=name, max_uses=maximum, current_uses=maximum, reset_on=reset
        )
        for name, maximum, reset in grants.resources
    )

    worn = _equipped_armor(items, grants)
    rows: dict[int, CharacterInventoryItem] = {}
    for index, grant in enumerate(items):
        rows[index] = CharacterInventoryItem.objects.create(
            character=character,
            equipment=grant.equipment,
            quantity=grant.quantity,
            equipped=index in worn,
            parent=rows.get(grant.parent),
            notes=grant.source,
        )

    CharacterCurrency.objects.update_or_create(
        character=character,
        defaults=equipment_resolver.split_coins(gold) | {"electrum": 0, "platinum": 0},
    )
    _write_abilities(character, draft)
    _write_character(character, draft)


def _write_abilities(character: Character, draft: Draft) -> None:
    base = ability_resolver.base_scores(draft)
    bonus = ability_resolver.bonus_scores(draft)
    final = ability_resolver.final_scores(draft)
    rows = []
    for ability in tables.ABILITIES:
        field = tables.ABILITY_FIELDS[ability]
        setattr(character, field, final[ability])
        name = field
        rows.append(
            CharacterAbilityScoreIncrease(
                character=character,
                ability=name,
                amount=base[ability],
                source="base",
                granted_at_level=1,
            )
        )
        if bonus[ability]:
            rows.append(
                CharacterAbilityScoreIncrease(
                    character=character,
                    ability=name,
                    amount=bonus[ability],
                    source="background",
                    granted_at_level=1,
                )
            )
        manual_delta = final[ability] - base[ability] - bonus[ability]
        if manual_delta:
            rows.append(
                CharacterAbilityScoreIncrease(
                    character=character,
                    ability=name,
                    amount=manual_delta,
                    source="manual",
                    granted_at_level=1,
                )
            )
    CharacterAbilityScoreIncrease.objects.bulk_create(rows)


def _write_character(character: Character, draft: Draft) -> None:
    character.size = species_resolver.size(draft)
    character.experience_points = tables.xp_for_level(draft.level)
    if draft.klass:
        con = tables.ability_modifier(character.constitution)
        character.max_hit_points = max(1, tables.hp_first_level(draft.klass.hit_die, con))
        character.current_hit_points = character.max_hit_points
    character.save()

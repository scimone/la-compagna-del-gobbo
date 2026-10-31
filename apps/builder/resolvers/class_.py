"""What the chosen class hands a level-1 character (SRD steps 1, 2 and 5)."""

from apps.rules.models import ClassLevel, Feature, Language, OptionalFeature, Spell

from ..class_spec import REFERENCE_FEATURES, OrderOption, spec_for
from ..services.store import Draft
from . import abilities
from .grants import Grants, SpellRow
from .proficiency import class_armor_categories, class_weapon_proficiency, named_tool_ids
from .spell import option_source, option_spell_flags, option_spell_grant

_SPELLS_AT_LEVEL_1 = 1


def chosen_order(draft: Draft) -> OrderOption | None:
    """The Divine/Primal Order option picked, if the class has one and it has been picked."""
    if not draft.klass:
        return None
    slug = draft.get("class.order")
    return next((o for o in spec_for(draft.klass.id).orders if _slug(o.feature) == slug), None)


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def class_row(draft: Draft) -> ClassLevel | None:
    return ClassLevel.objects.filter(klass=draft.klass, level=draft.level).first()


def cantrip_count(draft: Draft) -> int:
    row, order = class_row(draft), chosen_order(draft)
    return (row.cantrips_known or 0) + (order.extra_cantrips if order else 0) if row else 0


def prepared_count(draft: Draft) -> int:
    row = class_row(draft)
    return (row.spells_known_or_prepared or 0) if row else 0


def weapon_proficiency(draft: Draft):
    """The class's weapon proficiency plus whatever the chosen order adds (Protector/Warden)."""
    prof = class_weapon_proficiency(draft.klass)
    order = chosen_order(draft)
    prof.categories.update(order.weapon_categories if order else ())
    return prof


def armor_categories(draft: Draft) -> set[str]:
    order = chosen_order(draft)
    return class_armor_categories(draft.klass) | set(order.armor_categories if order else ())


def _resource_max(draft: Draft, maximum: tuple) -> int:
    kind, arg = maximum
    if kind == "column":
        return int(class_row(draft).columns.get(arg, 0) or 0)
    if kind == "per_level":
        return arg * draft.level
    if kind == "ability_mod_min1":
        return max(1, abilities.modifiers(draft)[arg])
    return arg  # "fixed"


def class_grants(draft: Draft, grants: Grants) -> None:
    klass = draft.klass
    if klass is None:
        return
    spec = spec_for(klass.id)
    for ability in klass.saving_throw_abilities.all():
        grants.add_proficiency("saving_throw", ability.id)
    for category in armor_categories(draft):
        grants.add_proficiency("armor", category)
    weapons = weapon_proficiency(draft)
    for category in weapons.categories:
        grants.add_proficiency("weapon", category)
    for category, properties in weapons.filtered:
        grants.add_proficiency("weapon", f"{category}:{','.join(sorted(properties))}")

    for tool_id in [*named_tool_ids(klass.tool_proficiencies), *draft.get("class.tools", [])]:
        grants.add_proficiency("tool", tool_id)
    for skill_id in draft.get("class.skills", []):
        grants.add_proficiency("skill", skill_id)
    for skill_id in draft.get("class.expertise", []):
        grants.add_proficiency("skill", skill_id, "expertise")

    order = chosen_order(draft)
    unchosen = {o.feature for o in spec.orders} - ({order.feature} if order else set())
    skipped = unchosen | REFERENCE_FEATURES.get(klass.id, set())
    for feature in Feature.objects.filter(
        class_level__klass=klass, class_level__level=_SPELLS_AT_LEVEL_1
    ).order_by("pk"):
        if feature.name_en not in skipped:
            grants.features.append(feature)

    if style := draft.get("class.fighting_style"):
        from apps.rules.models import Feat

        grants.feats.append((Feat.objects.get(id=style), "class"))
    grants.optional_features.extend(
        OptionalFeature.objects.filter(id__in=draft.get("class.invocations", []))
    )

    for language_id in [*spec.languages, draft.get("class.language")]:
        grants.add_language(language_id)

    source = f"class:{klass.id}"
    for name, maximum, reset_on in ((r.name, r.maximum, r.reset_on) for r in spec.resources):
        grants.resources.append((name, _resource_max(draft, maximum), reset_on))

    book = draft.get("class.spellbook", [])
    prepared = set(draft.get("class.spells", []))
    for spell_id in draft.get("class.cantrips", []):
        grants.add_spell(SpellRow(spell_id, source, klass.id))
    for spell_id in book:
        grants.add_spell(
            SpellRow(spell_id, source, klass.id, prepared=spell_id in prepared, in_spellbook=True)
        )
    for spell_id in prepared - set(book):
        grants.add_spell(SpellRow(spell_id, source, klass.id))
    for spell_id in spec.always_prepared:
        grants.add_spell(SpellRow(spell_id, source, klass.id, always_prepared=True))

    # Invocations that give spells (Pact of the Chain, Armor of Shadows, Pact of the Tome...).
    for option in grants.optional_features:
        grant = option_spell_grant(option)
        if not grant:
            continue
        for spell_id in grant.fixed:
            grants.add_spell(
                SpellRow(
                    spell_id,
                    option_source(option.id),
                    klass.id,
                    **option_spell_flags(grant, spell_id),
                )
            )
        for pick in grant.picks:
            for spell_id in draft.get(f"class.opt.{option.id}.{pick.key}", []):
                grants.add_spell(
                    SpellRow(
                        spell_id,
                        option_source(option.id),
                        klass.id,
                        always_prepared=pick.key == "rituals",
                    )
                )


def language_options(draft: Draft):
    """Languages the Rogue's free pick may choose: any, minus what the character already knows."""
    return Language.objects.exclude(id__in=known_languages(draft)).order_by("name")


def known_languages(draft: Draft) -> list[str]:
    from ..tables import COMMON_LANGUAGE_ID

    spec = spec_for(draft.klass.id) if draft.klass else None
    return [COMMON_LANGUAGE_ID, *draft.get("languages", []), *(spec.languages if spec else ())]


def spell_pool(draft: Draft, level: int):
    return Spell.objects.filter(level=level, classes__contains=[draft.klass.name_en]).order_by(
        "name"
    )

"""SRD steps 1, 2 and 4: class, background, species, languages, starting equipment, alignment.

Every `save_*` validates first and writes nothing on error (returns the `Issue`s); on success it
stores the picks and recomputes the character's grants (`effects.apply`). Changing a class,
background or species forgets the picks that depended on it (`clear_choices`) - the wizard then
shows them as outstanding again rather than keeping answers to a question that changed.
"""

import secrets

from django.utils.translation import gettext as _

from apps.characters.models import Character, CharacterClass
from apps.rules.models import Background, Class, Equipment, Feat, Language, Skill, Species

from .. import tables
from ..resolvers import equipment as equipment_resolver
from ..resolvers import feat as feat_resolver
from ..resolvers import held as held_resolver
from ..resolvers import species as species_resolver
from ..resolvers.proficiency import background_tool_grant, tool_options
from ..resolvers.spell import class_spell_list
from . import effects
from .store import Draft, Issue, clear_choices, set_choice

_rng = secrets.SystemRandom()


def _unknown(step: str, what: str) -> list[Issue]:
    return [Issue(step, "unknown", _("Unknown %(what)s.") % {"what": what})]


# --- class ------------------------------------------------------------------------------------


def select_class(character: Character, class_id: str) -> list[Issue]:
    klass = Class.objects.filter(id=class_id).first()
    if klass is None:
        return _unknown("class", _("class"))
    CharacterClass.objects.filter(character=character).delete()
    CharacterClass.objects.create(character=character, klass=klass, level=1, is_starting_class=True)
    clear_choices(character, "class.", "equipment.class", "equipment.groups")
    effects.apply(character)
    return []


# --- background --------------------------------------------------------------------------------


def select_background(character: Character, background_id: str) -> list[Issue]:
    background = Background.objects.filter(id=background_id).first()
    if background is None:
        return _unknown("background", _("background"))
    character.background = background
    character.save(update_fields=["background", "updated_at"])
    clear_choices(character, "background.", "equipment.background", "equipment.groups")
    _forget_ability_bonus(character)
    effects.apply(character)
    return []


def _forget_ability_bonus(character: Character) -> None:
    state = dict(Draft(character).get("abilities") or {})
    if state.pop("bonus", None) is not None:
        set_choice(character, "abilities", state)


def save_background_choices(
    character: Character, *, tool: str = "", feat: dict | None = None
) -> list[Issue]:
    if tool:
        set_choice(character, "background.tool", tool)
    if feat is not None:
        set_choice(character, "background.feat", feat)
    problems = background_issues(Draft(character))
    effects.apply(character)
    return problems


def background_issues(draft: Draft) -> list[Issue]:
    if draft.background is None:
        return [Issue("background", "missing", _("Choose a background."), "background")]
    found: list[Issue] = []
    _fixed, pick = background_tool_grant(draft.background)
    if pick:
        tool = draft.get("background.tool")
        options = {e.id for e in tool_options(pick[0])} - held_resolver.held(
            draft, exclude=("background",)
        )["tools"]
        if tool not in options:
            found.append(
                Issue(
                    "background", "missing_tool", _("Choose a tool proficiency."), "background.tool"
                )
            )
    if draft.background.feat:
        found += feat_pick_issues(
            "background",
            draft,
            draft.background.feat,
            dict(draft.get("background.feat") or {}),
            "background.feat",
            fixed_variant=draft.background.feat_variant,
        )
    return found


# --- feats' sub-choices (shared by background and species) ---------------------------------------


def feat_pick_issues(
    step, draft, feat: Feat, chosen: dict, path: str, *, fixed_variant: str = ""
) -> list[Issue]:
    found: list[Issue] = []
    exclude = (path,)
    held = held_resolver.held(draft, exclude=exclude)
    variant = fixed_variant or chosen.get("variant", "")
    for pick in feat_resolver.picks(feat, variant):
        if pick.key == "variant" and fixed_variant:
            continue
        value = chosen.get(pick.key)
        values = value if isinstance(value, list) else ([value] if value else [])
        where = f"{path}.{pick.key}"
        if len(values) != pick.count or len(set(values)) != len(values):
            found.append(
                Issue(
                    step,
                    "wrong_count",
                    _("Choose %(count)d for %(feat)s.") % {"count": pick.count, "feat": feat.name},
                    where,
                )
            )
            continue
        if pick.kind in ("variant", "ability"):
            valid = set(pick.options)
        elif pick.kind == "spell":
            valid = {s.id for s in class_spell_list(pick.class_name, pick.level)}
        elif pick.kind == "tool":
            pool = pick.options or [e.id for e in tool_options(pick.tool_kinds)]
            valid = set(pool) - held["tools"]
        else:  # skill_or_tool, stored as "skill:arcana" / "tool:flute"
            valid = {f"skill:{s}" for s in held_resolver.all_skill_ids() - held["skills"]}
            valid |= {
                f"tool:{e.id}"
                for e in Equipment.objects.filter(type_id__in=["t", "at", "gs", "ins"])
                if e.id not in held["tools"]
            }
        if not set(values) <= valid:
            found.append(
                Issue(
                    step,
                    "invalid_choice",
                    _("One of your choices for %(feat)s isn't available.") % {"feat": feat.name},
                    where,
                )
            )
    return found


# --- species -----------------------------------------------------------------------------------


def select_species(character: Character, species_id: str) -> list[Issue]:
    species = Species.objects.filter(id=species_id).first()
    if species is None:
        return _unknown("species", _("species"))
    character.species = species
    character.size = species.size[0] if len(species.size) == 1 else ""
    character.save(update_fields=["species", "size", "updated_at"])
    clear_choices(character, "species.")
    effects.apply(character)
    return []


def save_species_choices(character: Character, **choices) -> list[Issue]:
    """Any of `size`, `lineage`, `skill`, `spell_ability`, `cantrip` (list), `feat` (dict)."""
    for key, value in choices.items():
        set_choice(character, f"species.{key}", value)
    if "size" in choices:
        character.size = choices["size"]
        character.save(update_fields=["size", "updated_at"])
    problems = species_issues(Draft(character))
    effects.apply(character)
    return problems


def species_issues(draft: Draft) -> list[Issue]:
    species = draft.species
    if species is None:
        return [Issue("species", "missing", _("Choose a species."), "species")]
    found: list[Issue] = []
    if len(species.size) > 1 and draft.get("species.size") not in species.size:
        found.append(Issue("species", "missing_size", _("Choose a size."), "species.size"))
    if species.lineages and species_resolver.chosen_lineage(draft) is None:
        found.append(Issue("species", "missing_lineage", _("Choose a lineage."), "species.lineage"))
    options = species_resolver.spell_ability_options(draft)
    if options and draft.get("species.spell_ability") not in options:
        found.append(
            Issue(
                "species",
                "missing_spell_ability",
                _("Choose your spellcasting ability."),
                "species.spell_ability",
            )
        )
    picks = [p for g in species_resolver.spell_grants(draft) for p in g.picks]
    if picks:
        chosen = draft.get("species.cantrip", [])
        valid = {s.id for p in picks for s in class_spell_list(p.class_name, p.level)}
        if len(chosen) != sum(p.count for p in picks) or not set(chosen) <= valid:
            found.append(
                Issue("species", "missing_cantrip", _("Choose your cantrip."), "species.cantrip")
            )
    for choice in species.choice_definitions.filter(kind__in=["skills", "feats"]):
        if choice.kind == "skills":
            skill = draft.get("species.skill")
            options = set(choice.options) or held_resolver.all_skill_ids()
            options -= held_resolver.held(draft, exclude=("species",))["skills"]
            if skill not in options:
                found.append(
                    Issue(
                        "species",
                        "missing_skill",
                        _("Choose a skill proficiency."),
                        "species.skill",
                    )
                )
        else:
            extra = dict(draft.get("species.feat") or {})
            feat = Feat.objects.filter(id=extra.get("feat"), category="Origin").first()
            taken = draft.background.feat_id if draft.background else None
            if feat is None or (feat.id == taken and not feat_resolver.is_repeatable(feat)):
                found.append(
                    Issue("species", "missing_feat", _("Choose an Origin feat."), "species.feat")
                )
            else:
                found += feat_pick_issues("species", draft, feat, extra, "species.feat")
    return found


# --- languages ---------------------------------------------------------------------------------


def save_languages(character: Character, language_ids: list[str]) -> list[Issue]:
    set_choice(character, "languages", list(language_ids))
    problems = languages_issues(Draft(character))
    effects.apply(character)
    return problems


def roll_languages(character: Character) -> list[str]:
    """Fill the language slots by rolling 1d12 on the SRD table; a language already known is
    re-rolled (D6). Keeps any language the player already picked."""
    picked = list(Draft(character).get("languages") or [])
    while len(picked) < tables.EXTRA_LANGUAGES_AT_CREATION:
        result = tables.LANGUAGE_D12[_rng.randint(1, 12)]
        if result not in picked:
            picked.append(result)
    set_choice(character, "languages", picked)
    effects.apply(character)
    return picked


def languages_issues(draft: Draft) -> list[Issue]:
    picked = draft.get("languages") or []
    valid = set(tables.STANDARD_LANGUAGE_IDS)
    if (
        len(picked) != tables.EXTRA_LANGUAGES_AT_CREATION
        or len(set(picked)) != len(picked)
        or not set(picked) <= valid
    ):
        return [
            Issue(
                "languages",
                "wrong_languages",
                _("Choose two different standard languages besides Common."),
                "languages",
            )
        ]
    return []


def language_choices():
    return Language.objects.filter(id__in=tables.STANDARD_LANGUAGE_IDS).order_by("name")


# --- equipment ---------------------------------------------------------------------------------


def save_equipment(
    character: Character, *, class_option: str, background_option: str, groups: dict | None = None
) -> list[Issue]:
    set_choice(character, "equipment.class", class_option)
    set_choice(character, "equipment.background", background_option)
    set_choice(character, "equipment.groups", dict(groups or {}))
    problems = equipment_issues(Draft(character))
    effects.apply(character)
    return problems


def equipment_issues(draft: Draft) -> list[Issue]:
    found: list[Issue] = []
    for source in equipment_resolver.SOURCES:
        obj = equipment_resolver.source_object(draft, source)
        if obj is None:
            continue
        letter = draft.get(f"equipment.{source}")
        if letter not in equipment_resolver.option_rows(obj):
            found.append(
                Issue(
                    "equipment",
                    "missing_option",
                    _("Choose a starting equipment option."),
                    f"equipment.{source}",
                )
            )
    _items, _gold, problems = equipment_resolver.resolve(draft)
    for code, path in problems:
        if code == "missing_group_pick":
            found.append(Issue("equipment", code, _("Choose which item you get."), path))
    return found


# --- alignment ---------------------------------------------------------------------------------


def save_alignment(character: Character, code: str) -> list[Issue]:
    if code not in tables.ALIGNMENT_CODES:
        return [Issue("alignment", "unknown", _("Unknown alignment."), "alignment")]
    character.alignment = code
    character.save(update_fields=["alignment", "updated_at"])
    return []


def alignment_issues(draft: Draft) -> list[Issue]:
    if draft.character.alignment not in tables.ALIGNMENT_CODES:
        return [Issue("alignment", "missing", _("Choose an alignment."), "alignment")]
    return []


def alignment_warnings(draft: Draft) -> list[Issue]:
    if draft.character.alignment in tables.EVIL_ALIGNMENT_CODES:
        return [
            Issue(
                "alignment",
                "evil",
                _("The rules assume player characters aren't evil - talk to your GM first."),
                "alignment",
            )
        ]
    return []


def skill_ids() -> set[str]:
    return set(Skill.objects.values_list("id", flat=True))

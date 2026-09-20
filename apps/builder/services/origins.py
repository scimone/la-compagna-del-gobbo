"""SRD steps 1, 2 and 4: class, background, species, languages, starting equipment, alignment.

Every `save_*` validates first and writes nothing on error (returns the `Issue`s); on success it
stores the picks and recomputes the character's grants (`effects.apply`). Changing a class,
background or species forgets the picks that depended on it (`clear_choices`) - the wizard then
shows them as outstanding again rather than keeping answers to a question that changed.
"""

import secrets

from django.utils.translation import gettext as _

from apps.characters.models import Character, CharacterClass
from apps.rules.models import Ability, Background, Class, Equipment, Feat, Language, Skill, Species

from .. import tables
from ..resolvers import equipment as equipment_resolver
from ..resolvers import feat as feat_resolver
from ..resolvers import held as held_resolver
from ..resolvers import species as species_resolver
from ..resolvers.proficiency import background_tool_grant, tool_options
from ..resolvers.spell import class_spell_list
from . import effects
from .store import Draft, Issue, Picker, clear_choices, picker_issues, set_choice, stored

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


def background_pickers(draft: Draft) -> list[Picker]:
    if draft.background is None:
        return []
    pickers: list[Picker] = []
    _fixed, pick = background_tool_grant(draft.background)
    if pick:
        blocked = held_resolver.held(draft, exclude=("background",))["tools"]
        pickers.append(
            Picker(
                "background.tool",
                _("Tool proficiency"),
                1,
                [(e.id, e.name) for e in tool_options(pick[0]) if e.id not in blocked],
                stored(draft, "background.tool", True),
                single=True,
                kind="equipment",
            )
        )
    if draft.background.feat:
        pickers += feat_pickers(
            draft,
            draft.background.feat,
            "background.feat",
            fixed_variant=draft.background.feat_variant,
        )
    return pickers


def background_issues(draft: Draft) -> list[Issue]:
    if draft.background is None:
        return [Issue("background", "missing", _("Choose a background."), "background")]
    return picker_issues("background", background_pickers(draft))


# --- feats' sub-choices (shared by background and species) ---------------------------------------

_PICK_LABELS = {
    "variant": _("Spell list"),
    "spell_ability": _("Spellcasting ability"),
    "cantrips": _("Cantrips"),
    "spell": _("Spell"),
    "tools": _("Tools"),
    "proficiencies": _("Skills or tools"),
}


def _ability_names() -> dict[str, str]:
    return {a.id: a.name for a in Ability.objects.all()}


def feat_pickers(draft: Draft, feat: Feat, path: str, *, fixed_variant: str = "") -> list[Picker]:
    """The pickers for one feat's own sub-choices, stored in the dict at `path`."""
    chosen = dict(draft.get(path) or {})
    variant = fixed_variant or chosen.get("variant", "")
    held = held_resolver.held(draft, exclude=(path,))
    pickers: list[Picker] = []
    # "Magic Initiate (Druid)": say which list the spells come from - it is fixed by the background
    # (Guide -> Druid), so a spell that isn't on that list (Blade Ward) is rightly not offered.
    spell_list = Class.objects.filter(id=variant).first() if variant else None
    feat_title = f"{feat.name} ({spell_list.name})" if spell_list else feat.name
    list_hint = (
        _("The spells come from the %(list)s spell list.") % {"list": spell_list.name}
        if spell_list
        else ""
    )
    for pick in feat_resolver.picks(feat, variant):
        if pick.key == "variant" and fixed_variant:
            continue
        if pick.kind == "variant":
            candidates = [(v, v.title()) for v in pick.options]
        elif pick.kind == "ability":
            names = _ability_names()
            candidates = [(a, names.get(a, a)) for a in pick.options]
        elif pick.kind == "spell":
            candidates = [(s.id, s.name) for s in class_spell_list(pick.class_name, pick.level)]
        elif pick.kind == "tool":
            pool = (
                Equipment.objects.filter(id__in=pick.options)
                if pick.options
                else tool_options(pick.tool_kinds)
            )
            candidates = [
                (e.id, e.name) for e in pool.order_by("name") if e.id not in held["tools"]
            ]
        else:  # skill_or_tool, stored as "skill:arcana" / "tool:flute"
            candidates = [
                (f"skill:{s.id}", s.name)
                for s in Skill.objects.order_by("name")
                if s.id not in held["skills"]
            ] + [
                (f"tool:{e.id}", e.name)
                for e in Equipment.objects.filter(type_id__in=["t", "at", "gs", "ins"]).order_by(
                    "name"
                )
                if e.id not in held["tools"]
            ]
        key = f"{path}.{pick.key}"
        single = pick.kind in ("variant", "ability") or pick.key == "spell"
        pickers.append(
            Picker(
                key,
                f"{feat_title}: {_PICK_LABELS.get(pick.key, pick.key)}",
                pick.count,
                candidates,
                stored(draft, key, single),
                single,
                kind={"spell": "spell", "tool": "equipment"}.get(pick.kind, "plain"),
                refresh=pick.kind == "variant",  # the list decides which spells are offered
                hint=list_hint if pick.kind == "spell" else "",
            )
        )
    return pickers


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


def species_pickers(draft: Draft) -> list[Picker]:
    species = draft.species
    if species is None:
        return []
    pickers: list[Picker] = []

    def add(key, label, count, candidates, single=False, **extra):
        pickers.append(
            Picker(key, label, count, candidates, stored(draft, key, single), single, **extra)
        )

    if len(species.size) > 1:
        labels = {"S": _("Small"), "M": _("Medium")}
        add("species.size", _("Size"), 1, [(c, labels.get(c, c)) for c in species.size], True)
    if species.lineages:
        add(
            "species.lineage",
            _("Lineage"),
            1,
            [(lin["key"], lin["label"]) for lin in species.lineages],
            True,
            refresh=True,  # the lineage decides the cantrip, speed and darkvision
        )
    if options := species_resolver.spell_ability_options(draft):
        names = _ability_names()
        add(
            "species.spell_ability",
            _("Spellcasting ability"),
            1,
            [(a, names.get(a, a)) for a in options],
            True,
        )
    if spell_picks := [p for g in species_resolver.spell_grants(draft) for p in g.picks]:
        pool = {
            (s.id, s.name) for p in spell_picks for s in class_spell_list(p.class_name, p.level)
        }
        add(
            "species.cantrip",
            _("Cantrip"),
            sum(p.count for p in spell_picks),
            sorted(pool, key=lambda c: c[1]),
            kind="spell",
        )
    for choice in species.choice_definitions.filter(kind__in=["skills", "feats"]):
        if choice.kind == "skills":
            allowed = set(choice.options) or held_resolver.all_skill_ids()
            blocked = held_resolver.held(draft, exclude=("species",))["skills"]
            skills = Skill.objects.filter(id__in=allowed - blocked).order_by("name")
            add(
                "species.skill",
                _("Skill proficiency"),
                choice.count or 1,
                [(s.id, s.name) for s in skills],
                True,
                kind="skill",
                refresh=True,  # the skill decides who can take Expertise, and what else is offered
            )
        else:
            taken = draft.background.feat if draft.background else None
            feats = [
                (f.id, f.name)
                for f in feat_resolver.origin_feats()
                if taken is None or f.id != taken.id or feat_resolver.is_repeatable(f)
            ]
            add("species.feat.feat", _("Origin feat"), 1, feats, True, kind="feat", refresh=True)
            extra = dict(draft.get("species.feat") or {})
            if feat := Feat.objects.filter(id=extra.get("feat"), category="Origin").first():
                pickers += feat_pickers(draft, feat, "species.feat")
    return pickers


def species_issues(draft: Draft) -> list[Issue]:
    if draft.species is None:
        return [Issue("species", "missing", _("Choose a species."), "species")]
    return picker_issues("species", species_pickers(draft))


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

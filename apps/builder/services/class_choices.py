"""SRD step 5, "Registrare i privilegi di classe": the level-1 choices the class asks for.

`pickers(draft)` is the single description of what is being asked - how many, from which
candidates, what is selected - and both the screen and `issues()` are built from it, so what the
form offers and what validation accepts cannot drift apart.
"""

from django.utils.translation import gettext as _

from apps.characters.models import Character
from apps.rules.models import ChoiceDefinition, Equipment, OptionalFeature

from ..class_spec import spec_for
from ..resolvers import class_ as class_resolver
from ..resolvers import feat as feat_resolver
from ..resolvers import held as held_resolver
from ..resolvers.proficiency import tool_options
from ..resolvers.spell import max_spell_level
from . import effects
from .store import Draft, Issue, Picker, picker_issues, set_choice

STEP = "choices"


def _selected(draft: Draft, key: str, single: bool) -> list[str]:
    value = draft.get(key)
    if single:
        return [value] if value else []
    return list(value or [])


def _skill_candidates(draft: Draft):
    from apps.rules.models import Skill

    choice = ChoiceDefinition.objects.filter(klass=draft.klass, kind="skills").first()
    pool = (
        Skill.objects.filter(id__in=choice.options)
        if choice and choice.options
        else Skill.objects.all()
    )
    blocked = held_resolver.held(draft, exclude=("class",))["skills"]
    return choice.count if choice else 0, [
        (s.id, s.name) for s in pool.order_by("name") if s.id not in blocked
    ]


def _mastery_candidates(draft: Draft, spec):
    weapons = (
        Equipment.objects.filter(
            weapon_category__in=["simple", "martial"],
            type_id__in=["m"] if spec.weapon_mastery.melee_only else ["m", "r"],
            masteries__isnull=False,
        )
        .distinct()
        .order_by("name")
        .prefetch_related("properties")
    )
    if spec.weapon_mastery.proficient_only:
        proficiency = class_resolver.weapon_proficiency(draft)
        weapons = [w for w in weapons if proficiency.covers(w)]
    return [(w.id, w.name) for w in weapons]


def _eligible_invocations(draft: Draft):
    """Invocations with no prerequisite beyond a class level we already meet. Anything gated on a
    spell or another invocation can't be met with a single first pick."""
    result = []
    for feature in OptionalFeature.objects.filter(feature_type="Eldritch Invocation").order_by(
        "name"
    ):
        ok = True
        for prerequisite in feature.prerequisite:
            level = prerequisite.get("level", {}).get("level") if "level" in prerequisite else None
            if set(prerequisite) - {"level"} or (level or 0) > draft.level:
                ok = False
        if ok:
            result.append((feature.id, feature.name))
    return result


def pickers(draft: Draft) -> list[Picker]:
    klass = draft.klass
    if klass is None:
        return []
    spec = spec_for(klass.id)
    found: list[Picker] = []

    def add(key, label, count, candidates, single=False):
        found.append(Picker(key, label, count, candidates, _selected(draft, key, single), single))

    count, candidates = _skill_candidates(draft)
    if count:
        add("class.skills", _("Skills"), count, candidates)
    if spec.tool_pick:
        blocked = held_resolver.held(draft, exclude=("class",))["tools"]
        add(
            "class.tools",
            _("Tool proficiency"),
            spec.tool_pick.count,
            [
                (e.id, e.name)
                for e in tool_options(list(spec.tool_pick.kinds))
                if e.id not in blocked
            ],
        )
    if spec.orders:
        add(
            "class.order",
            _(spec.order_feature),
            1,
            [(_slug(o.feature), o.feature) for o in spec.orders],
            single=True,
        )
    if spec.weapon_mastery:
        add(
            "class.weapon_mastery",
            _("Weapon Mastery"),
            spec.weapon_mastery.count,
            _mastery_candidates(draft, spec),
        )
    if spec.fighting_style:
        add(
            "class.fighting_style",
            _("Fighting Style"),
            1,
            [(f.id, f.name) for f in feat_resolver.fighting_style_feats()],
            single=True,
        )
    if spec.invocations:
        add(
            "class.invocations",
            _("Eldritch Invocation"),
            spec.invocations,
            _eligible_invocations(draft),
        )
    if spec.extra_languages:
        add(
            "class.language",
            _("Language"),
            spec.extra_languages,
            [(lang.id, lang.name) for lang in class_resolver.language_options(draft)],
            single=True,
        )

    cantrips = class_resolver.cantrip_count(draft)
    if cantrips:
        add(
            "class.cantrips",
            _("Cantrips"),
            cantrips,
            [(s.id, s.name) for s in class_resolver.spell_pool(draft, 0)],
        )
    highest = max_spell_level(klass, draft.level)
    always = set(spec.always_prepared)
    leveled = [
        (s.id, s.name)
        for level in range(1, highest + 1)
        for s in class_resolver.spell_pool(draft, level)
        if s.id not in always
    ]
    if spec.spellbook:
        add("class.spellbook", _("Spellbook"), spec.spellbook, [c for c in leveled])
        book = set(draft.get("class.spellbook", []))
        add(
            "class.spells",
            _("Prepared spells"),
            class_resolver.prepared_count(draft),
            [c for c in leveled if c[0] in book],
        )
    elif class_resolver.prepared_count(draft):
        add("class.spells", _("Prepared spells"), class_resolver.prepared_count(draft), leveled)

    if spec.expertise:
        skills = held_resolver.held(draft)["skills"]
        from apps.rules.models import Skill

        add(
            "class.expertise",
            _("Expertise"),
            spec.expertise,
            [(s.id, s.name) for s in Skill.objects.filter(id__in=skills).order_by("name")],
        )
    return found


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def issues(draft: Draft) -> list[Issue]:
    return picker_issues(STEP, pickers(draft)) if draft.klass else []


def save(character: Character, **values) -> list[Issue]:
    """Store any of the class's picks by short key (`skills`, `weapon_mastery`, `spells`, ...)."""
    for key, value in values.items():
        set_choice(character, f"class.{key}", value)
    # A pick other pickers depend on invalidates them (prepared spells come from the book).
    draft = Draft(character)
    if "spellbook" in values:
        book = set(values["spellbook"])
        set_choice(
            character, "class.spells", [s for s in draft.get("class.spells", []) if s in book]
        )
    problems = issues(Draft(character))
    effects.apply(character)
    return problems

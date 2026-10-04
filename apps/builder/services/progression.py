"""Levelling up a finished character: what the next level gives, what it asks the player to
choose, and writing it down.

A finished character's rows are its own (see `effects.py`), so unlike the creation wizard this does
not recompute anything from choices: `plan()` works out the next level from the rows as they are
(what the character already has decides what may still be picked) and `commit()` adds to them, in
one transaction. Both take the same `values` - what the level-up form submitted, `{picker key:
[values]}` - so what the page offers and what is accepted are one list (`Plan.sections`).

The rules are the SRD's "Advancement" and "Multiclassing" chapters; what `db/` only states in prose
(when a class asks for a choice, what a multiclass entry grants) is in `progression_spec.py`.

What a level-up does, in order: choose the class to advance (a new one needs the multiclass
minimums), hit points (average or a roll, plus Constitution and per-level bonuses), the subclass at
its level, the class features of the level (and the subclass's), the feat / Ability Score
Improvement at its levels, the class's own choices (Expertise, Fighting Style, Weapon Mastery,
Maneuvers, Metamagic, Invocations, ...), spells (cantrips, prepared spells, the spellbook, a swap),
the limited-use resources, and Experience Points.
"""

import json
import random
from collections.abc import Mapping
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.characters.models import (
    Character,
    CharacterAbilityScoreIncrease,
    CharacterChoice,
    CharacterClass,
    CharacterFeat,
    CharacterFeature,
    CharacterLanguage,
    CharacterOptionalFeature,
    CharacterProficiency,
    CharacterResource,
    CharacterSense,
    CharacterSpell,
)
from apps.characters.services import play
from apps.rules.models import (
    Ability,
    ChoiceDefinition,
    Class,
    ClassLevel,
    Equipment,
    Feat,
    Feature,
    Language,
    OptionalFeature,
    Sense,
    Skill,
    Subclass,
    SubclassLevel,
)

from .. import progression_spec as spec
from .. import tables
from ..class_spec import spec_for
from ..resolvers import feat as feat_resolver
from ..resolvers import species as species_resolver
from ..resolvers.proficiency import WeaponProficiency, tool_options
from ..resolvers.spell import class_spell_list, max_spell_level, spell_id
from . import feature_resources
from .store import Issue, Picker, picker_issues

Values = Mapping[str, list[str]]

_ABILITY_FIELD = tables.ABILITY_FIELDS
_ARMOR_TYPE = {"light": "la", "medium": "ma", "heavy": "ha", "shield": "s"}


# --- what the character has now ---------------------------------------------------------------


def total_level(character: Character) -> int:
    return sum(character.classes.values_list("level", flat=True)) or 1


def scores(character: Character) -> dict[str, int]:
    return {a: getattr(character, _ABILITY_FIELD[a]) for a in tables.ABILITIES}


def can_level_up(character: Character) -> bool:
    """A finished character below the maximum level whose Experience Points reach the next one."""
    return character.status == Character.STATUS_COMPLETE and xp_ready(character)


def xp_ready(character: Character) -> bool:
    """Whether the Experience Points already reach the next level."""
    level = total_level(character)
    return level < spec.MAX_LEVEL and character.experience_points >= tables.xp_for_level(level + 1)


def _meets_primary(klass: Class, ability_scores: dict[str, int]) -> bool:
    ids = [a.id for a in klass.primary_abilities.all()]
    has = [ability_scores.get(a, 0) >= spec.MULTICLASS_MINIMUM for a in ids]
    return all(has) if klass.primary_ability_conjunction == "and" else any(has)


def multiclass_shortfall(character: Character, klass: Class) -> list[str]:
    """Names of the classes (the new one and the current ones) whose primary ability is below 13."""
    ability_scores = scores(character)
    classes = [klass, *(row.klass for row in character.classes.select_related("klass"))]
    return [k.name for k in classes if not _meets_primary(k, ability_scores)]


def class_options(character: Character) -> list[dict]:
    """Every class the next level may go into: `{klass, level (0 = new), allowed, reason}`."""
    rows = {row.klass_id: row for row in character.classes.select_related("klass")}
    options = []
    for klass in Class.objects.prefetch_related("primary_abilities"):
        row = rows.get(klass.id)
        reason = ""
        if row is None:
            short = multiclass_shortfall(character, klass)
            if short:
                reason = _("Needs 13 in the primary ability of %(classes)s.") % {
                    "classes": ", ".join(short)
                }
        options.append(
            {
                "klass": klass,
                "level": row.level if row else 0,
                "allowed": not reason,
                "reason": reason,
            }
        )
    return options


# --- the plan ---------------------------------------------------------------------------------


@dataclass
class Section:
    key: str
    title: str
    hint: str = ""
    pickers: list[Picker] = field(default_factory=list)


@dataclass
class Plan:
    character: Character
    klass: Class
    old_level: int
    new_level: int
    total_after: int
    entering: bool
    subclass: Subclass | None
    hp: dict
    features: list[Feature]
    sections: list[Section]
    issues: list[Issue]
    #: Everything the level-up will do, as short lines for the confirmation ("+2 cantrips", ...).
    summary: list[str]
    #: The extra state `commit()` needs, worked out once here.
    extra: dict = field(default_factory=dict)

    @property
    def pickers(self) -> list[Picker]:
        return [p for section in self.sections for p in section.pickers]

    @property
    def ready(self) -> bool:
        return not self.issues


class _Ctx:
    """Everything `plan()` reads about the character, loaded once."""

    def __init__(self, character: Character, klass: Class, values: Values):
        self.character = character
        self.klass = klass
        self.values = values
        self.rows = {r.klass_id: r for r in character.classes.select_related("klass", "subclass")}
        self.row = self.rows.get(klass.id)
        self.entering = self.row is None
        self.old_level = self.row.level if self.row else 0
        self.new_level = self.old_level + 1
        self.total_after = total_level(character) + 1
        self.scores = scores(character)
        proficiencies = list(character.proficiencies.all())
        self.skills = {p.name: p.level for p in proficiencies if p.category == "skill"}
        self.tools = {p.name for p in proficiencies if p.category == "tool"}
        self.weapons = {p.name for p in proficiencies if p.category == "weapon"}
        self.armor = {p.name for p in proficiencies if p.category == "armor"}
        self.languages = set(character.languages.values_list("language_id", flat=True))
        self.feats = list(character.feats.select_related("feat"))
        self.feat_ids = {f.feat_id for f in self.feats}
        self.optional = set(
            character.optional_features.values_list("optional_feature_id", flat=True)
        )
        self.spells = {s.spell_id: s for s in character.spells.select_related("spell")}
        self.subclass = self.row.subclass if self.row else None
        self.new_subclass: Subclass | None = None
        self.notes: list[str] = []

    def get(self, key: str) -> list[str]:
        return [v for v in self.values.get(key, []) if v]

    def one(self, key: str) -> str:
        chosen = self.get(key)
        return chosen[0] if chosen else ""

    def picker(
        self, key, label, count, candidates, *, single=False, kind="plain", **extra
    ) -> Picker:
        selected = self.get(key)[:1] if single else self.get(key)
        return Picker(key, label, count, candidates, selected, single, kind=kind, **extra)


def _names(qs, attr="name") -> list[tuple[str, str]]:
    return [(o.id, getattr(o, attr)) for o in qs]


def _skill_candidates(ctx: _Ctx, ids=None, *, held: bool = False) -> list[tuple[str, str]]:
    """Skills to choose from: `ids` (or all), minus what the character already has unless `held`."""
    pool = Skill.objects.all() if ids is None else Skill.objects.filter(id__in=list(ids))
    return [(s.id, s.name) for s in pool.order_by("name") if held or s.id not in ctx.skills]


def _ability_names() -> dict[str, str]:
    return {a.id: a.name for a in Ability.objects.all()}


# ---- hit points ------------------------------------------------------------------------------


def hit_point_bonus_per_level(character: Character) -> int:
    """Hit points every level adds beyond the die: Tough (2), Dwarven Toughness (1)."""
    bonus = sum(
        spec.HP_PER_LEVEL_FEATS.get(feat_id, 0)
        for feat_id in character.feats.values_list("feat_id", flat=True)
    )
    names = set(character.features.values_list("feature__name_en", flat=True))
    return bonus + sum(n for name, n in spec.HP_PER_LEVEL_FEATURES.items() if name in names)


def _hp_plan(ctx: _Ctx, new_con_mod: int, old_con_mod: int, subclass: Subclass | None) -> dict:
    die = ctx.klass.hit_die
    fixed = tables.hit_die_faces(die) // 2 + 1
    mode = ctx.one("lu.hp_mode") or "fixed"
    roll = None
    if mode == "roll":
        try:
            roll = int(ctx.one("lu.hp_roll"))
        except ValueError:
            roll = None
    base = fixed if mode == "fixed" else (roll or 0)
    per_level = hit_point_bonus_per_level(ctx.character)
    gain = max(1, base + new_con_mod) + per_level
    # Draconic Sorcery: +1 per Sorcerer level (3 at once when the subclass is taken).
    if subclass and (ctx.klass.id, subclass.name_en) in spec.HP_PER_CLASS_LEVEL_SUBCLASS:
        extra = spec.HP_PER_CLASS_LEVEL_SUBCLASS[(ctx.klass.id, subclass.name_en)]
        gain += extra * (ctx.new_level if ctx.new_subclass else 1)
    retro = (ctx.total_after - 1) * (new_con_mod - old_con_mod)
    return {
        "die": die,
        "faces": tables.hit_die_faces(die),
        "fixed": fixed,
        "mode": mode,
        "roll": roll,
        "con_mod": new_con_mod,
        "per_level": per_level,
        "retro": retro,
        "gain": gain,
    }


# ---- feats -----------------------------------------------------------------------------------


def _prerequisite_met(ctx: _Ctx, feat: Feat, level_after: int) -> bool:
    """Any one of the feat's alternative prerequisite objects must hold. What can't be checked
    from the sheet (prose in `otherSummary`) is not a reason to refuse."""
    if not feat.prerequisite:
        return True
    casts = any(r.klass.spellcasting_ability_id for r in ctx.rows.values()) or (
        ctx.klass.spellcasting_ability_id is not None
    )
    for alt in feat.prerequisite:
        ok = level_after >= alt.get("level", 0)
        if ok and alt.get("ability"):
            ok = any(
                ctx.scores.get(a, 0) >= n for entry in alt["ability"] for a, n in entry.items()
            )
        if ok and alt.get("proficiency"):
            ok = all(
                v in ctx.armor
                for entry in alt["proficiency"]
                for k, v in entry.items()
                if k == "armor"
            )
        if ok and alt.get("spellcasting2020"):
            ok = casts
        if ok and alt.get("spellcasting"):
            ok = casts
        if ok:
            return True
    return False


def eligible_feats(ctx: _Ctx, categories: tuple[str, ...]) -> list[Feat]:
    feats = []
    for feat in Feat.objects.filter(category__in=categories).order_by("name"):
        if feat.id in ctx.feat_ids and not feat_resolver.is_repeatable(feat):
            continue
        if _prerequisite_met(ctx, feat, ctx.total_after):
            feats.append(feat)
    feats.sort(key=lambda f: (f.id != "ability-score-improvement", f.category != "General", f.name))
    return feats


def _feat_ability_options(feat: Feat) -> list[str]:
    choice = ChoiceDefinition.objects.filter(feat=feat, kind="ability_scores").first()
    return list(choice.options) if choice else []


def _feat_skill_pick(feat: Feat) -> tuple[list[str] | None, int] | None:
    """`(allowed skill ids or None for any, count)` when the feat grants a skill of choice."""
    for entry in feat.grants.get("skillProficiencies", []):
        if "choose" in entry:
            choose = entry["choose"]
            return list(choose.get("from", [])) or None, choose.get("count", 1)
        if "any" in entry:
            return None, int(entry["any"])
    return None


def _cap(feat: Feat | None) -> int:
    return spec.EPIC_BOON_CAP if feat and feat.category == "Epic Boon" else spec.ABILITY_CAP


def _feat_pickers(ctx: _Ctx, feat: Feat, prefix: str) -> list[Picker]:
    """The picks `feat` asks for, keyed under `prefix`: an ability, skills, expertise, and the
    spell/ability choices `feat_resolver.picks` describes (Magic Initiate-style feats)."""
    found: list[Picker] = []
    names = _ability_names()
    cap = _cap(feat)
    if feat.id == "ability-score-improvement":
        mode = ctx.picker(
            f"{prefix}.asi_mode",
            _("Ability Score Improvement"),
            1,
            [("plus2", _("+2 to one ability score")), ("plus1", _("+1 to two ability scores"))],
            single=True,
            refresh=True,
        )
        found.append(mode)
        able = [(a, names[a]) for a in tables.ABILITIES if ctx.scores[a] < cap]
        if mode.selected == ["plus2"]:
            found.append(
                ctx.picker(
                    f"{prefix}.asi_plus2",
                    _("The ability score to raise by 2"),
                    1,
                    [(a, n) for a, n in able if ctx.scores[a] + 2 <= cap],
                    single=True,
                )
            )
        elif mode.selected == ["plus1"]:
            found.append(
                ctx.picker(
                    f"{prefix}.asi_plus1", _("The two ability scores to raise by 1"), 2, able
                )
            )
    else:
        options = _feat_ability_options(feat)
        if options:
            found.append(
                ctx.picker(
                    f"{prefix}.ability",
                    _("Ability score +1"),
                    1,
                    [(a, names[a]) for a in options if ctx.scores[a] < cap],
                    single=True,
                )
            )
    skill = _feat_skill_pick(feat)
    if skill is not None:
        allowed, count = skill
        found.append(
            ctx.picker(
                f"{prefix}.skills",
                _("Skill proficiency"),
                count,
                _skill_candidates(ctx, allowed),
                kind="skill",
            )
        )
    if feat.grants.get("expertise"):
        proficient = [s for s, level in ctx.skills.items() if level == "proficient"]
        chosen_skills = set(ctx.get(f"{prefix}.skills"))
        pool = sorted({*proficient, *chosen_skills})
        found.append(
            ctx.picker(
                f"{prefix}.expertise",
                _("Expertise"),
                1,
                [(s.id, s.name) for s in Skill.objects.filter(id__in=pool).order_by("name")],
                kind="skill",
            )
        )
    # Magic Initiate: which spell list the spells come from decides which spells are offered.
    variant = ""
    if feat_resolver.variants(feat):
        found.insert(
            0,
            ctx.picker(
                f"{prefix}.variant",
                _("Spell list"),
                1,
                [(v, v.title()) for v in feat_resolver.variants(feat)],
                single=True,
                refresh=True,
            ),
        )
        variant = ctx.one(f"{prefix}.variant")
    for pick in feat_resolver.picks(feat, variant):
        if pick.kind == "variant":
            continue
        if pick.kind == "ability":
            found.append(
                ctx.picker(
                    f"{prefix}.{pick.key}",
                    _("Spellcasting ability"),
                    1,
                    [(a, names.get(a, a)) for a in pick.options],
                    single=True,
                )
            )
        elif pick.kind == "spell":
            owned = set(ctx.spells)
            found.append(
                ctx.picker(
                    f"{prefix}.{pick.key}",
                    _("Spells") if pick.level else _("Cantrips"),
                    pick.count,
                    [
                        (s.id, s.name)
                        for s in class_spell_list(pick.class_name, pick.level)
                        if s.id not in owned
                    ],
                    single=pick.key == "spell",
                    kind="spell",
                )
            )
        elif pick.kind == "tool":
            pool = (
                Equipment.objects.filter(id__in=pick.options)
                if pick.options
                else tool_options(pick.tool_kinds)
            )
            found.append(
                ctx.picker(
                    f"{prefix}.tools",
                    _("Tool proficiency"),
                    pick.count,
                    [(e.id, e.name) for e in pool.order_by("name") if e.id not in ctx.tools],
                    kind="equipment",
                )
            )
    return found


def _asi_deltas(ctx: _Ctx, feat: Feat | None) -> dict[str, int]:
    """The ability increases the chosen feat asks for, `{ability: amount}` (empty if not chosen)."""
    if feat is None:
        return {}
    if feat.id == "ability-score-improvement":
        mode = ctx.one("lu.feat.asi_mode")
        if mode == "plus2" and ctx.one("lu.feat.asi_plus2"):
            return {ctx.one("lu.feat.asi_plus2"): 2}
        if mode == "plus1":
            return {a: 1 for a in ctx.get("lu.feat.asi_plus1")}
        return {}
    ability = ctx.one("lu.feat.ability")
    return {ability: 1} if ability else {}


# ---- class choices ---------------------------------------------------------------------------


def _class_feature_rows(klass: Class, level: int) -> list[Feature]:
    return list(
        Feature.objects.filter(class_level__klass=klass, class_level__level=level).order_by("pk")
    )


def _has_marker(rows: list[Feature], *names: str) -> bool:
    return any(f.name in names for f in rows)


def _is_placeholder(feature: Feature, klass: Class) -> bool:
    return (
        feature.name_en in spec.ASI_FEATURES
        or feature.name_en == spec.SUBCLASS_MARKER
        or feature.name_en == f"{klass.name_en} Subclass"
        or feature.name_en in spec.REFERENCE_FEATURES
    )


def _optional(ctx: _Ctx, feature_type: str):
    return OptionalFeature.objects.filter(feature_type=feature_type).order_by("name")


def _invocation_candidates(ctx: _Ctx, level_after: int, exclude: set[str]) -> list[tuple[str, str]]:
    """Invocations whose prerequisites (Warlock level, another invocation, a damaging cantrip)
    the character meets and that they don't have already."""
    known_cantrip_damage = any(
        s.spell.level == 0 and "{@damage" in json.dumps(s.spell.entries)
        for s in ctx.spells.values()
    )
    have = ctx.optional | set(ctx.get("lu.invocations")) | set(ctx.get("lu.invocation_in"))
    result = []
    for feature in _optional(ctx, "Eldritch Invocation"):
        if feature.id in exclude or feature.id in ctx.optional:
            continue
        ok = True
        for prerequisite in feature.prerequisite:
            level = prerequisite.get("level", {}).get("level", 0) if "level" in prerequisite else 0
            ok = ok and level_after >= level
            for ref in prerequisite.get("optionalfeature", []):
                ok = ok and spell_id(ref) in have
            if prerequisite.get("spell"):
                ok = ok and known_cantrip_damage
        if ok:
            result.append((feature.id, feature.name))
    return result


def _weapon_candidates(
    ctx: _Ctx, melee_only: bool, proficient_only: bool, exclude
) -> list[tuple[str, str]]:
    weapons = (
        Equipment.objects.filter(
            weapon_category__in=["simple", "martial"],
            type_id__in=["m"] if melee_only else ["m", "r"],
            masteries__isnull=False,
        )
        .distinct()
        .order_by("name")
        .prefetch_related("properties")
    )
    if proficient_only:
        from ..services.derived_stats import weapon_proficiency

        proficiency: WeaponProficiency = weapon_proficiency(ctx.weapons)
        weapons = [w for w in weapons if proficiency.covers(w)]
    return [(w.id, w.name) for w in weapons if w.id not in exclude]


def _known_masteries(character: Character) -> list[str]:
    row = CharacterChoice.objects.filter(character=character, key="class.weapon_mastery").first()
    return list(row.value or []) if row else []


def _column(ctx: _Ctx, level: int, header: str) -> int:
    if level <= 0:
        return 0
    row = ClassLevel.objects.filter(klass=ctx.klass, level=level).first()
    try:
        return int((row.columns or {}).get(header, 0) or 0) if row else 0
    except (TypeError, ValueError):
        return 0


def _class_sections(ctx: _Ctx) -> list[Section]:
    """The choices of the class's own next level (or, entering a class, its first)."""
    klass, new, old = ctx.klass, ctx.new_level, ctx.old_level
    sections: list[Section] = []
    class_spec = spec_for(klass.id)
    subclass = ctx.subclass or ctx.new_subclass
    subclass_name = subclass.name_en if subclass else ""

    # Expertise ...
    expertise = spec.EXPERTISE_AT.get(klass.id, {}).get(new, 0)
    if ctx.entering:
        expertise = class_spec.expertise
    scholar = (klass.id, new) == spec.WIZARD_SCHOLAR
    deft = (klass.id, new) == spec.RANGER_DEFT_EXPLORER
    picks: list[Picker] = []
    if expertise or scholar or deft:
        proficient = [s for s, lv in ctx.skills.items() if lv == "proficient"]
        pool = proficient
        count = expertise or 1
        if scholar:
            pool = [s for s in proficient if s in spec.WIZARD_SCHOLAR_SKILLS]
        picks.append(
            ctx.picker(
                "lu.expertise",
                _("Expertise"),
                count,
                [(s.id, s.name) for s in Skill.objects.filter(id__in=pool).order_by("name")],
                kind="skill",
            )
        )
    if deft:
        picks.append(
            ctx.picker(
                "lu.languages",
                _("Languages"),
                2,
                [
                    (x.id, x.name)
                    for x in Language.objects.exclude(id__in=ctx.languages).order_by("name")
                ],
            )
        )
    # Barbarian Primal Knowledge
    if (klass.id, new) == spec.BARBARIAN_PRIMAL_KNOWLEDGE:
        picks.append(
            ctx.picker(
                "lu.skills",
                _("Skill proficiency"),
                1,
                _skill_candidates(ctx, spec.BARBARIAN_SKILLS),
                kind="skill",
            )
        )
    # Subclass one-offs
    for kind, count in spec.SUBCLASS_PICKS.get((klass.id, subclass_name), {}).get(new, []):
        if kind == "skills":
            picks.append(
                ctx.picker(
                    "lu.skills", _("Skill proficiency"), count, _skill_candidates(ctx), kind="skill"
                )
            )
        elif kind == "fighter_skill":
            picks.append(
                ctx.picker(
                    "lu.skills",
                    _("Skill proficiency"),
                    count,
                    _skill_candidates(ctx, spec.FIGHTER_SKILLS),
                    kind="skill",
                )
            )
        elif kind == "artisan_tool":
            picks.append(
                ctx.picker(
                    "lu.tool",
                    _("Tool proficiency"),
                    count,
                    [
                        (e.id, e.name)
                        for e in tool_options(["anyArtisansTool"]).order_by("name")
                        if e.id not in ctx.tools
                    ],
                    kind="equipment",
                )
            )
    if picks:
        sections.append(Section("skills", _("Skills and languages"), pickers=picks))

    # Divine / Primal Order (when entering Cleric or Druid)
    if ctx.entering and class_spec.orders:
        sections.append(
            Section(
                "order",
                _(class_spec.order_feature),
                pickers=[
                    ctx.picker(
                        "lu.order",
                        _(class_spec.order_feature),
                        1,
                        [
                            (o.feature.lower().replace(" ", "-"), o.feature)
                            for o in class_spec.orders
                        ],
                        single=True,
                    )
                ],
            )
        )

    # Fighting Style
    styles: list[Picker] = []
    if (
        (ctx.entering and class_spec.fighting_style)
        or spec.FIGHTING_STYLE_AT.get(klass.id) == new
        or (spec.SUBCLASS_FIGHTING_STYLE_AT.get((klass.id, subclass_name)) == new)
    ):
        categories = ["Fighting Style"]
        if extra := spec.CLASS_FIGHTING_STYLE_CATEGORY.get(klass.id):
            categories.append(extra)
        pool = [
            f
            for f in Feat.objects.filter(category__in=categories).order_by("name")
            if f.id not in ctx.feat_ids
        ]
        styles.append(
            ctx.picker(
                "lu.style",
                _("Fighting Style"),
                1,
                _names(pool),
                single=True,
                kind="feat",
                refresh=True,
            )
        )
        chosen = Feat.objects.filter(id=ctx.one("lu.style")).first()
        if chosen:
            styles += _feat_pickers(ctx, chosen, "lu.style")
        sections.append(Section("style", _("Fighting Style"), pickers=styles))

    # Weapon Mastery
    mastery = class_spec.weapon_mastery
    if mastery and (
        ctx.entering or _column(ctx, new, "Weapon Mastery") > _column(ctx, old, "Weapon Mastery")
    ):
        count = (
            mastery.count
            if ctx.entering
            else _column(ctx, new, "Weapon Mastery") - _column(ctx, old, "Weapon Mastery")
        )
        sections.append(
            Section(
                "mastery",
                _("Weapon Mastery"),
                pickers=[
                    ctx.picker(
                        "lu.weapon_mastery",
                        _("Weapon Mastery"),
                        count,
                        _weapon_candidates(
                            ctx,
                            mastery.melee_only,
                            mastery.proficient_only,
                            set(_known_masteries(ctx.character)),
                        ),
                        kind="equipment",
                    )
                ],
            )
        )

    # Class options: Metamagic, Maneuvers, Invocations
    options: list[Picker] = []
    if klass.id == "sorcerer" and new in spec.METAMAGIC_KNOWN:
        count = spec.METAMAGIC_KNOWN[new] - spec.METAMAGIC_KNOWN.get(
            max((lv for lv in spec.METAMAGIC_KNOWN if lv < new), default=0), 0
        )
        options.append(
            ctx.picker(
                "lu.metamagic",
                _("Metamagic"),
                count,
                [(o.id, o.name) for o in _optional(ctx, "Metamagic") if o.id not in ctx.optional],
                kind="invocation",
            )
        )
    if klass.id == "sorcerer" and old and not ctx.entering:
        have = [(o.id, o.name) for o in _optional(ctx, "Metamagic") if o.id in ctx.optional]
        if have:
            options.append(
                ctx.picker(
                    "lu.metamagic_out",
                    _("Replace a Metamagic option"),
                    1,
                    have,
                    single=True,
                    optional=True,
                )
            )
            options.append(
                ctx.picker(
                    "lu.metamagic_in",
                    _("...with"),
                    1,
                    [
                        (o.id, o.name)
                        for o in _optional(ctx, "Metamagic")
                        if o.id not in ctx.optional
                    ],
                    single=True,
                    optional=True,
                )
            )
    if klass.id == "fighter" and subclass_name == "Battle Master" and new in spec.MANEUVERS_KNOWN:
        previous = spec.MANEUVERS_KNOWN.get(
            max((lv for lv in spec.MANEUVERS_KNOWN if lv < new), default=0), 0
        )
        maneuvers = [
            (o.id, o.name)
            for o in _optional(ctx, "Maneuver, Battle Master")
            if o.id not in ctx.optional
        ]
        options.append(
            ctx.picker(
                "lu.maneuvers",
                _("Maneuvers"),
                spec.MANEUVERS_KNOWN[new] - previous,
                maneuvers,
                kind="invocation",
            )
        )
    if klass.id == "fighter" and subclass_name == "Battle Master" and old >= 3:
        have = [
            (o.id, o.name)
            for o in _optional(ctx, "Maneuver, Battle Master")
            if o.id in ctx.optional
        ]
        options.append(
            ctx.picker(
                "lu.maneuver_out", _("Replace a maneuver"), 1, have, single=True, optional=True
            )
        )
        options.append(
            ctx.picker(
                "lu.maneuver_in",
                _("...with"),
                1,
                [
                    (o.id, o.name)
                    for o in _optional(ctx, "Maneuver, Battle Master")
                    if o.id not in ctx.optional
                ],
                single=True,
                optional=True,
            )
        )
    if klass.id == "warlock":
        now = _column(ctx, new, "Invocations") if not ctx.entering else class_spec.invocations
        before = _column(ctx, old, "Invocations") if not ctx.entering else 0
        if now > before:
            options.append(
                ctx.picker(
                    "lu.invocations",
                    _("Eldritch Invocation"),
                    now - before,
                    _invocation_candidates(ctx, new, set()),
                    kind="invocation",
                )
            )
        held = [
            (o.id, o.name) for o in _optional(ctx, "Eldritch Invocation") if o.id in ctx.optional
        ]
        if held and not ctx.entering:
            options.append(
                ctx.picker(
                    "lu.invocation_out",
                    _("Replace an invocation"),
                    1,
                    held,
                    single=True,
                    optional=True,
                )
            )
            options.append(
                ctx.picker(
                    "lu.invocation_in",
                    _("...with"),
                    1,
                    _invocation_candidates(ctx, new, {ctx.one("lu.invocation_out")}),
                    single=True,
                    optional=True,
                )
            )
    if options:
        sections.append(Section("options", _("Class options"), pickers=options))
    return sections


# ---- spells ----------------------------------------------------------------------------------


def _casting(ctx: _Ctx) -> dict | None:
    """How the levelled class casts, next to now: `{list, cantrips, prepared, max_level}` gained
    (Eldritch Knight / Arcane Trickster included once their subclass is known)."""
    klass, new, old = ctx.klass, ctx.new_level, ctx.old_level
    subclass = ctx.subclass or ctx.new_subclass
    third = spec.SUBCLASS_CASTING.get((klass.id, subclass.name_en)) if subclass else None
    if klass.spellcasting_ability_id:
        row_new = ClassLevel.objects.filter(klass=klass, level=new).first()
        row_old = ClassLevel.objects.filter(klass=klass, level=old).first() if old else None
        return {
            "list": klass.name,
            "cantrips": (row_new.cantrips_known or 0)
            - ((row_old.cantrips_known or 0) if row_old else 0),
            "prepared": (row_new.spells_known_or_prepared or 0)
            - ((row_old.spells_known_or_prepared or 0) if row_old else 0),
            "max_level": max_spell_level(klass, new),
        }
    if third and new >= 3:
        slots = third.slots[new - 1]
        return {
            "list": spec.SUBCLASS_CASTING_LIST,
            "cantrips": third.cantrips[new - 1] - third.cantrips[old - 1 if old else 0],
            "prepared": third.prepared[new - 1] - third.prepared[old - 1 if old else 0],
            "max_level": max((i + 1 for i, n in enumerate(slots) if n), default=0),
        }
    return None


def _spell_sections(ctx: _Ctx) -> list[Section]:
    klass, new = ctx.klass, ctx.new_level
    info = _casting(ctx)
    pickers: list[Picker] = []
    owned = set(ctx.spells)
    if info:
        class_list = info["list"]
        if info["cantrips"] > 0:
            pickers.append(
                ctx.picker(
                    "lu.cantrips",
                    _("Cantrips"),
                    info["cantrips"],
                    [(s.id, s.name) for s in class_spell_list(class_list, 0) if s.id not in owned],
                    kind="spell",
                )
            )
        leveled = [
            (s.id, s.name)
            for level in range(1, info["max_level"] + 1)
            for s in class_spell_list(class_list, level)
            if s.id not in owned
        ]
        book_picked = set(ctx.get("lu.spellbook"))
        if klass.id == "wizard":
            add = spec.WIZARD_SPELLBOOK_START if ctx.entering else spec.WIZARD_SPELLBOOK_PER_LEVEL
            pickers.append(
                ctx.picker(
                    "lu.spellbook", _("Spellbook"), add, list(leveled), kind="spell", refresh=True
                )
            )
            prepared_pool = [
                (s.spell_id, s.spell.name)
                for s in ctx.spells.values()
                if s.in_spellbook and not s.prepared and s.klass_id == "wizard"
            ] + [c for c in leveled if c[0] in book_picked]
        else:
            prepared_pool = leveled
        if info["prepared"] > 0:
            pickers.append(
                ctx.picker(
                    "lu.spells", _("Prepared spells"), info["prepared"], prepared_pool, kind="spell"
                )
            )
        if klass.id in spec.SWAP_SPELL_CLASSES or (
            ctx.subclass and klass.id in ("fighter", "rogue")
        ):
            mine = [
                (s.spell_id, s.spell.name)
                for s in ctx.spells.values()
                if s.klass_id == klass.id
                and s.prepared
                and not s.always_prepared
                and s.spell.level > 0
            ]
            if mine and not ctx.entering:
                pickers.append(
                    ctx.picker(
                        "lu.spell_out", _("Replace a spell"), 1, mine, single=True, optional=True
                    )
                )
                pickers.append(
                    ctx.picker(
                        "lu.spell_in",
                        _("...with"),
                        1,
                        leveled,
                        single=True,
                        optional=True,
                        kind="spell",
                    )
                )
    if klass.id == "warlock" and new in spec.MYSTIC_ARCANUM_AT:
        level = spec.MYSTIC_ARCANUM_AT[new]
        pickers.append(
            ctx.picker(
                "lu.arcanum",
                _("Mystic Arcanum (level %(level)d)") % {"level": level},
                1,
                [(s.id, s.name) for s in class_spell_list("Warlock", level) if s.id not in owned],
                single=True,
                kind="spell",
            )
        )
    return [Section("spells", _("Spells"), pickers=pickers)] if pickers else []


# ---- multiclass entry ------------------------------------------------------------------------


def _entry_sections(ctx: _Ctx) -> list[Section]:
    """What entering a class as an additional one gives (SRD "Multiclass Proficiencies")."""
    gain = spec.MULTICLASS_GAINS[ctx.klass.id]
    pickers: list[Picker] = []
    if gain.skills:
        pickers.append(
            ctx.picker(
                "lu.entry_skills",
                _("Skill proficiency"),
                gain.skills,
                _skill_candidates(ctx, gain.skill_list or None),
                kind="skill",
            )
        )
    if gain.instrument:
        pickers.append(
            ctx.picker(
                "lu.entry_tool",
                _("Musical instrument"),
                1,
                [
                    (e.id, e.name)
                    for e in tool_options(["anyMusicalInstrument"]).order_by("name")
                    if e.id not in ctx.tools
                ],
                single=True,
                kind="equipment",
            )
        )
    if spec_for(ctx.klass.id).extra_languages:
        pickers.append(
            ctx.picker(
                "lu.language",
                _("Language"),
                1,
                [
                    (x.id, x.name)
                    for x in Language.objects.exclude(id__in=ctx.languages).order_by("name")
                ],
                single=True,
            )
        )
    return (
        [Section("entry", _("New class"), _("Proficiencies you gain as a new class."), pickers)]
        if pickers
        else []
    )


# ---- the plan --------------------------------------------------------------------------------


_SCHOOL_CODES = {
    "A": "Abjuration",
    "C": "Conjuration",
    "D": "Divination",
    "E": "Enchantment",
    "V": "Evocation",
    "I": "Illusion",
    "N": "Necromancy",
    "T": "Transmutation",
}


def _subclass_picks(ctx: _Ctx, subclass: Subclass | None) -> list[dict]:
    """The spells a subclass lets the player choose at this level (`{"choose": "level=0;1;2|
    class=Wizard|school=A"}` in `additionalSpells.known`: a Wizard school's Savant) as
    `{levels, class_name, school}` - the ones of this level, or every one up to it when the
    subclass has just been taken."""
    picks = []
    for entry in subclass.additional_spells if subclass else ():
        for key, items in (entry.get("known") or {}).items():
            level = _level_of(key)
            if level != ctx.new_level and not (ctx.new_subclass and level <= ctx.new_level):
                continue
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and "choose" in item:
                    parts = dict(p.split("=", 1) for p in item["choose"].split("|") if "=" in p)
                    picks.append(
                        {
                            "levels": [int(n) for n in parts.get("level", "0").split(";")],
                            "class_name": parts.get("class", ""),
                            "school": _SCHOOL_CODES.get(parts.get("school", ""), ""),
                        }
                    )
    return picks


def _subclass_pick_pickers(ctx: _Ctx, subclass: Subclass | None) -> list[Picker]:
    owned = set(ctx.spells)
    found = []
    for index, pick in enumerate(_subclass_picks(ctx, subclass)):
        pool = [
            (s.id, s.name)
            for level in pick["levels"]
            for s in class_spell_list(pick["class_name"], level)
            if s.id not in owned and (not pick["school"] or s.school == pick["school"])
        ]
        found.append(
            ctx.picker(
                f"lu.savant.{index}",
                _("Spell from your subclass"),
                1,
                pool,
                single=True,
                kind="spell",
            )
        )
    return found


def plan(character: Character, class_id: str, values: Values | None = None) -> Plan:
    """The next level in `class_id` for `character`, and what is still to decide."""
    values = values or {}
    klass = Class.objects.prefetch_related("primary_abilities").get(id=class_id)
    ctx = _Ctx(character, klass, values)
    issues: list[Issue] = []
    if total_level(character) >= spec.MAX_LEVEL:
        raise ValueError("already at the maximum level")
    if ctx.entering and (short := multiclass_shortfall(character, klass)):
        raise ValueError("multiclass requirements not met: " + ", ".join(short))

    # subclass
    sections: list[Section] = []
    marker_rows = _class_feature_rows(klass, ctx.new_level)
    needs_subclass = (
        not ctx.entering
        and ctx.subclass is None
        and _has_marker(marker_rows, f"{klass.name} Subclass")
    )
    if needs_subclass:
        pool = list(klass.subclasses.all())
        sections.append(
            Section(
                "subclass",
                klass.subclass_title or _("Subclass"),
                pickers=[
                    ctx.picker(
                        "lu.subclass",
                        klass.subclass_title or _("Subclass"),
                        1,
                        [(str(s.pk), s.name) for s in pool],
                        single=True,
                        refresh=True,
                    )
                ],
            )
        )
        chosen = next((s for s in pool if str(s.pk) == ctx.one("lu.subclass")), None)
        ctx.new_subclass = chosen
        # a subclass with named spell lists (Circle of the Land) asks which one
        if chosen and any(e.get("name") for e in chosen.additional_spells):
            sections[-1].pickers.append(
                ctx.picker(
                    "lu.land",
                    _("Land"),
                    1,
                    [(e["name"], e["name"]) for e in chosen.additional_spells if e.get("name")],
                    single=True,
                )
            )
    subclass = ctx.subclass or ctx.new_subclass
    if savant := _subclass_pick_pickers(ctx, subclass):
        sections.append(Section("savant", _("Subclass spells"), pickers=savant))

    # feat / ability score improvement
    asi_rows = [f for f in marker_rows if f.name in spec.ASI_FEATURES]
    feat = None
    if asi_rows and not ctx.entering:
        categories = (
            ("General", "Epic Boon")
            if any(f.name_en == "Epic Boon" for f in asi_rows)
            else ("General",)
        )
        feats = eligible_feats(ctx, categories)
        feat_picker = ctx.picker(
            "lu.feat",
            _("Feat"),
            1,
            _names(feats),
            single=True,
            kind="feat",
            refresh=True,
            hint=_("An Ability Score Improvement is a feat: pick it to raise your ability scores."),
        )
        feat = next((f for f in feats if f.id == ctx.one("lu.feat")), None)
        section = Section("feat", _("Ability Score Improvement or feat"), pickers=[feat_picker])
        if feat:
            section.pickers += _feat_pickers(ctx, feat, "lu.feat")
        sections.append(section)

    # scores after this level, for hit points (a Constitution raise counts at once)
    deltas = _asi_deltas(ctx, feat)
    cap = _cap(feat)
    after = {a: min(cap, ctx.scores[a] + deltas.get(a, 0)) for a in tables.ABILITIES}
    old_con, new_con = (
        tables.ability_modifier(ctx.scores["con"]),
        tables.ability_modifier(after["con"]),
    )

    if ctx.entering:
        sections += _entry_sections(ctx)
    sections += _class_sections(ctx)
    sections += _spell_sections(ctx)

    # hit points come first on the page
    hp = _hp_plan(ctx, new_con, old_con, subclass)
    sections.insert(0, Section("hp", _("Hit points")))

    # features gained
    features = _features_gained(ctx, subclass)

    # validation of every picker, then the pairs, ability bounds and the hit point roll
    pickers = [p for s in sections for p in s.pickers]
    issues += picker_issues("levelup", pickers)
    issues += _extra_issues(ctx, sections, feat, deltas, hp)

    plan_ = Plan(
        character=character,
        klass=klass,
        old_level=ctx.old_level,
        new_level=ctx.new_level,
        total_after=ctx.total_after,
        entering=ctx.entering,
        subclass=subclass,
        hp=hp,
        features=features,
        sections=sections,
        issues=issues,
        summary=[],
        extra={"feat": feat, "deltas": deltas, "cap": cap, "ctx": ctx},
    )
    plan_.summary = _summary(plan_)
    return plan_


def _grant_species_traits(character: Character, total: int) -> None:
    """Species traits that start at a higher character level (Draconic Flight at 5) arrive when
    that level is reached; creation leaves them out (see `species.start_level()`)."""
    if not character.species_id:
        return
    for feature in character.species.feature_rows.filter(choice_option=False):
        if 1 < species_resolver.start_level(feature) <= total:
            CharacterFeature.objects.get_or_create(
                character=character, feature=feature, defaults={"granted_at_level": total}
            )


def _grant_land_feature(character: Character, subclass: Subclass, land: str, level: int) -> None:
    """The chosen land's own feature ("Circle of the Land Spells (Arid Land)") replaces the
    generic one listing every land's table - and the previous land's, when it changes."""
    own = Feature.objects.filter(
        subclass_level__subclass=subclass, choice_option=True, name_en__endswith=f"({land})"
    ).first()
    if own is None:
        return
    base = own.name_en.rsplit(" (", 1)[0]
    CharacterFeature.objects.filter(
        Q(feature__name_en=base) | Q(feature__name_en__startswith=f"{base} ("),
        character=character,
        feature__subclass_level__subclass=subclass,
    ).exclude(feature=own).delete()
    CharacterFeature.objects.get_or_create(
        character=character, feature=own, defaults={"granted_at_level": level}
    )


def _features_gained(ctx: _Ctx, subclass: Subclass | None) -> list[Feature]:
    klass = ctx.klass
    rows = [f for f in _class_feature_rows(klass, ctx.new_level) if not _is_placeholder(f, klass)]
    if ctx.entering:
        class_spec = spec_for(klass.id)
        chosen = ctx.one("lu.order")
        unchosen = {
            o.feature for o in class_spec.orders if o.feature.lower().replace(" ", "-") != chosen
        }
        rows = [f for f in rows if f.name not in unchosen]
    sub_levels = []
    if subclass:
        if ctx.new_subclass:
            sub_levels = SubclassLevel.objects.filter(subclass=subclass, level__lte=ctx.new_level)
        else:
            sub_levels = SubclassLevel.objects.filter(subclass=subclass, level=ctx.new_level)
    for level in sub_levels:
        # a choice's alternatives (each land of Circle of the Land) are granted when chosen
        rows += list(level.feature_rows.filter(choice_option=False).order_by("pk"))
    return rows


def _extra_issues(ctx: _Ctx, sections, feat, deltas, hp) -> list[Issue]:
    issues: list[Issue] = []
    keys = {p.key: p for s in sections for p in s.pickers}
    for a, b in (
        ("lu.metamagic_out", "lu.metamagic_in"),
        ("lu.maneuver_out", "lu.maneuver_in"),
        ("lu.invocation_out", "lu.invocation_in"),
        ("lu.spell_out", "lu.spell_in"),
    ):
        if a in keys and b in keys and bool(keys[a].selected) != bool(keys[b].selected):
            issues.append(
                Issue(
                    "levelup",
                    "swap",
                    _("A replacement needs both the choice to drop and its replacement."),
                    a,
                )
            )
    if feat and feat.id == "ability-score-improvement" and not deltas:
        issues.append(
            Issue(
                "levelup", "asi", _("Choose how to raise your ability scores."), "lu.feat.asi_mode"
            )
        )
    if hp["mode"] == "roll" and not (hp["roll"] and 1 <= hp["roll"] <= hp["faces"]):
        issues.append(
            Issue(
                "levelup",
                "hp_roll",
                _("Enter the number you rolled on the hit die (1-%(n)d).") % {"n": hp["faces"]},
                "lu.hp_roll",
            )
        )
    return issues


def _summary(plan_: Plan) -> list[str]:
    lines = [_("%(klass)s level %(level)d") % {"klass": plan_.klass.name, "level": plan_.new_level}]
    lines.append(_("+%(hp)d hit points") % {"hp": plan_.hp["gain"] + plan_.hp["retro"]})
    return lines


# --- committing -------------------------------------------------------------------------------


def roll_hit_die(faces: int) -> int:
    return random.randint(1, faces)


def _set_proficiency(
    character: Character, category: str, name: str, level: str = "proficient"
) -> None:
    row, created = CharacterProficiency.objects.get_or_create(
        character=character,
        category=category,
        name=name,
        defaults={"level": level, "skill_id": name if category == "skill" else None},
    )
    if not created and level == "expertise" and row.level != "expertise":
        row.level = "expertise"
        row.save(update_fields=["level"])


def _add_feat(character: Character, feat: Feat, level: int, source: str) -> None:
    CharacterFeat.objects.create(
        character=character, feat=feat, granted_at_level=level, source=source
    )
    grants = feat.grants
    for entry in grants.get("skillProficiencies", []):
        for skill_id, value in entry.items():
            if value is True and skill_id.replace(" ", "-") in {s.id for s in Skill.objects.all()}:
                _set_proficiency(character, "skill", skill_id.replace(" ", "-"))
    for entry in grants.get("armorProficiencies", []):
        for category, value in entry.items():
            if value is True:
                _set_proficiency(character, "armor", category)
    for entry in grants.get("weaponProficiencies", []):
        for category, value in entry.items():
            if value is True:
                _set_proficiency(character, "weapon", category)
    for entry in grants.get("senses", []):
        for sense, feet in entry.items():
            if Sense.objects.filter(id=sense).exists():
                CharacterSense.objects.create(
                    character=character, sense_id=sense, range_feet=feet, source=f"feat:{feat.id}"
                )
    for name in feat_resolver.fixed_weapon_grants(feat):
        _set_proficiency(character, "weapon", name)
    if feat.id == "boon-of-fortitude":  # "Your Hit Point maximum increases by 40"
        character.max_hit_points += 40
        character.current_hit_points += 40
        character.save(update_fields=["max_hit_points", "current_hit_points"])
    if feat.id == "boon-of-skill":  # "You gain proficiency in all skills"
        for skill in Skill.objects.all():
            _set_proficiency(character, "skill", skill.id)


def _add_spell(character, spell_id_, klass_id, source, **flags) -> None:
    CharacterSpell.objects.update_or_create(
        character=character,
        spell_id=spell_id_,
        defaults={"klass_id": klass_id, "source": source, **flags},
    )


def _apply_feat_picks(ctx: _Ctx, feat: Feat, prefix: str, level: int) -> None:
    character = ctx.character
    for skill_id in ctx.get(f"{prefix}.skills"):
        _set_proficiency(character, "skill", skill_id)
    for skill_id in ctx.get(f"{prefix}.expertise"):
        _set_proficiency(character, "skill", skill_id, "expertise")
    for tool_id in ctx.get(f"{prefix}.tools"):
        _set_proficiency(character, "tool", tool_id)
    if feat.id == "resilient" and ctx.one(f"{prefix}.ability"):
        _set_proficiency(character, "saving_throw", ctx.one(f"{prefix}.ability"))
    spell_ability = ctx.one(f"{prefix}.spell_ability")
    if spell_ability:
        # One entry per time the feat was taken (Magic Initiate can be taken again).
        key = f"levelup.feat.{feat.id}"
        taken = CharacterChoice.objects.filter(character=character, key__startswith=key).count()
        CharacterChoice.objects.update_or_create(
            character=character,
            key=key if not taken else f"{key}.{taken + 1}",
            defaults={"value": {"spell_ability": spell_ability}},
        )
    grant = feat_resolver.spell_grant_for(feat, ctx.one(f"{prefix}.variant"))
    source = f"feat:{feat.id}"
    if grant:
        for fixed in grant.fixed:
            _add_spell(character, fixed, None, source, prepared=True, always_prepared=True)
        for cantrip in ctx.get(f"{prefix}.cantrips"):
            _add_spell(character, cantrip, None, source, prepared=True)
        if ctx.one(f"{prefix}.spell"):
            _add_spell(
                character,
                ctx.one(f"{prefix}.spell"),
                None,
                source,
                prepared=True,
                always_prepared=True,
                free_cast=True,
            )


# ---- a feat added from the character sheet ---------------------------------------------------

_SHEET_PREFIX = "lu.feat"


def _sheet_ctx(character: Character, values: Values) -> _Ctx:
    klass = character.classes.select_related("klass").first().klass
    return _Ctx(character, klass, values)


def sheet_feat_pickers(character: Character, feat: Feat, values: Values) -> list[Picker]:
    """What adding `feat` by hand asks the player to choose (Magic Initiate's list and spells, a
    skill, an ability...), given what they have chosen so far in `values`. Empty for a feat that
    just is."""
    return _feat_pickers(_sheet_ctx(character, values), feat, _SHEET_PREFIX)


@transaction.atomic
def add_feat_from_sheet(character: Character, feat: Feat, values: Values) -> None:
    """Give the character `feat` with the choices it asks for (see `sheet_feat_pickers`), as the
    level-up would: its fixed grants, the spells, skills, tools and ability increase chosen.
    `ValueError` when it is already taken (and cannot be taken again) or a choice is missing or not
    one of the offered."""
    if character.feats.filter(feat=feat).exists() and not feat_resolver.is_repeatable(feat):
        raise ValueError(f"{feat.name} is already on the sheet")
    ctx = _sheet_ctx(character, values)
    problems = []
    for picker in _feat_pickers(ctx, feat, _SHEET_PREFIX):
        chosen = ctx.get(picker.key)
        needed = min(1 if picker.single else picker.count, len(picker.candidates))
        if (
            len(chosen) != needed
            or len(set(chosen)) != len(chosen)
            or not set(chosen) <= picker.candidate_ids
        ):
            problems.append(picker.label)
    if problems:
        raise ValueError("choose: " + ", ".join(problems))
    total = total_level(character)
    cap = _cap(feat)
    for ability, amount in _asi_deltas(ctx, feat).items():
        field_name = _ABILITY_FIELD[ability]
        current = getattr(character, field_name)
        applied = min(cap, current + amount) - current
        if applied:
            setattr(character, field_name, current + applied)
            CharacterAbilityScoreIncrease.objects.create(
                character=character,
                ability=field_name,
                amount=applied,
                source="feat",
                granted_at_level=total,
            )
    character.save()
    _add_feat(character, feat, total, play.FEATURE_SOURCE)
    _apply_feat_picks(ctx, feat, _SHEET_PREFIX, total)
    feature_resources.refresh(character)


def _resource_maximum(ctx: _Ctx, res: spec.LevelResource, level: int, mods: dict[str, int]) -> int:
    kind, arg = res.maximum
    if kind == "column":
        return _column(ctx, level, arg)
    if kind == "by_level":
        reached = [lv for lv in arg if lv <= level]
        return arg[max(reached)] if reached else 0
    if kind == "per_level":
        return arg * level
    if kind == "mod":
        return max(1, mods[arg])
    return tables.proficiency_bonus(ctx.total_after)  # "proficiency"


def _update_resources(
    ctx: _Ctx, level: int, subclass: Subclass | None, mods: dict[str, int]
) -> None:
    character = ctx.character
    wanted: dict[str, tuple[int, str]] = {}
    for res in spec.LEVEL_RESOURCES.get(ctx.klass.id, ()):
        if level < res.from_level or (
            res.subclass and (not subclass or subclass.name_en != res.subclass)
        ):
            continue
        maximum = _resource_maximum(ctx, res, level, mods)
        if maximum > 0:
            wanted[res.name] = (maximum, res.reset_on)  # a later row of the same name wins
    for name, (maximum, reset_on) in wanted.items():
        row = CharacterResource.objects.filter(character=character, name=name).first()
        if row is None:
            CharacterResource.objects.create(
                character=character,
                name=name,
                max_uses=maximum,
                current_uses=maximum,
                reset_on=reset_on,
            )
        else:
            row.current_uses = min(maximum, row.current_uses + max(0, maximum - row.max_uses))
            row.max_uses, row.reset_on = maximum, reset_on
            row.save(update_fields=["max_uses", "current_uses", "reset_on"])
    # Ranger / other resources that follow the proficiency bonus grow with any class's level
    for other in ctx.rows.values():
        if other.klass_id == ctx.klass.id:
            continue
        for res in spec.LEVEL_RESOURCES.get(other.klass_id, ()):
            if res.maximum[0] != "proficiency" or other.level < res.from_level:
                continue
            row = CharacterResource.objects.filter(character=character, name=res.name).first()
            maximum = tables.proficiency_bonus(ctx.total_after)
            if row and row.max_uses != maximum:
                row.current_uses += max(0, maximum - row.max_uses)
                row.max_uses = maximum
                row.save(update_fields=["max_uses", "current_uses"])


def _refs(node):
    """Every spell reference string inside a `known`/`innate`/`prepared` block, however nested
    (`{"ritual": [...]}`, `{"daily": {"1": [...]}}`, plain lists); a `{"choose": ...}` is a pick,
    not a reference."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)
    elif isinstance(node, dict) and "choose" not in node:
        for value in node.values():
            yield from _refs(value)


def _level_of(key: str) -> int:
    return 0 if key == "_" else int(key)


def _subclass_spells(ctx: _Ctx, subclass: Subclass, level: int, land: str) -> None:
    """The spells a subclass always has prepared (Domain, Oath, Circle, ...) up to `level`."""
    character = ctx.character
    source = f"subclass:{subclass.pk}"
    for entry in subclass.additional_spells:
        if entry.get("name") and entry["name"] != land:
            continue  # one of several named lists (Circle of the Land): only the chosen one
        for block, always in (("prepared", True), ("known", False), ("innate", True)):
            for key, refs in (entry.get(block) or {}).items():
                if _level_of(key) > level:
                    continue
                for ref in _refs(refs):
                    _add_spell(
                        character,
                        spell_id(ref),
                        ctx.klass.id,
                        source,
                        prepared=True,
                        always_prepared=always,
                    )


@transaction.atomic
def commit(character: Character, class_id: str, values: Values) -> Plan:
    """Apply the level-up `plan()` describes. Raises `ValueError` if it isn't ready."""
    character = Character.objects.select_for_update().get(pk=character.pk)
    plan_ = plan(character, class_id, values)
    if not plan_.ready:
        raise ValueError("; ".join(i.message for i in plan_.issues))
    ctx: _Ctx = plan_.extra["ctx"]
    klass, new, total = plan_.klass, plan_.new_level, plan_.total_after
    feat: Feat | None = plan_.extra["feat"]
    deltas: dict[str, int] = plan_.extra["deltas"]
    cap: int = plan_.extra["cap"]
    class_spec = spec_for(klass.id)
    subclass = plan_.subclass

    # the class row
    if ctx.entering:
        row = CharacterClass.objects.create(character=character, klass=klass, level=1)
    else:
        row = ctx.row
        row.level = new
    if ctx.new_subclass:
        row.subclass = ctx.new_subclass
    row.save()

    # hit points, XP
    hp = plan_.hp
    character.max_hit_points += hp["gain"] + hp["retro"]
    character.current_hit_points += hp["gain"] + hp["retro"]

    # ability scores
    for ability, amount in deltas.items():
        field_name = _ABILITY_FIELD[ability]
        current = getattr(character, field_name)
        applied = min(cap, current + amount) - current
        if applied:
            setattr(character, field_name, current + applied)
            CharacterAbilityScoreIncrease.objects.create(
                character=character,
                ability=field_name,
                amount=applied,
                source="feat" if feat else "level",
                granted_at_level=total,
            )
    threshold = tables.xp_for_level(total)
    character.experience_points = max(character.experience_points, threshold)
    character.save()
    play.grant_spell_changes(character, "level", {klass.id})  # SRD: change prepared spells
    mods = {
        a: tables.ability_modifier(getattr(character, _ABILITY_FIELD[a])) for a in tables.ABILITIES
    }

    # the feat
    if feat:
        _add_feat(character, feat, total, "levelup")
        _apply_feat_picks(ctx, feat, "lu.feat", total)

    # features
    for feature in plan_.features:
        CharacterFeature.objects.get_or_create(
            character=character, feature=feature, defaults={"granted_at_level": new}
        )
    _grant_species_traits(character, total)
    if subclass:
        land_key = f"subclass.{klass.id}.land"
        if ctx.new_subclass and ctx.one("lu.land"):
            CharacterChoice.objects.update_or_create(
                character=character, key=land_key, defaults={"value": ctx.one("lu.land")}
            )
            _grant_land_feature(character, subclass, ctx.one("lu.land"), new)
        for index in range(len(_subclass_picks(ctx, subclass))):
            for spell_key in ctx.get(f"lu.savant.{index}"):
                _add_spell(
                    character,
                    spell_key,
                    klass.id,
                    f"subclass:{subclass.pk}",
                    prepared=False,
                    in_spellbook=True,
                )
        stored = CharacterChoice.objects.filter(character=character, key=land_key).first()
        _subclass_spells(ctx, subclass, new, stored.value if stored else "")
        for grants in [spec.SUBCLASS_GRANTS.get((klass.id, subclass.name), {}).get(new)]:
            if not grants:
                continue
            for category in grants.get("armor", ()):
                _set_proficiency(character, "armor", category)
            for category in grants.get("weapons", ()):
                _set_proficiency(character, "weapon", category)
            for skill_id in grants.get("skills", ()):
                _set_proficiency(character, "skill", skill_id)
            for tool_id in grants.get("tools", ()):
                _set_proficiency(character, "tool", tool_id)

    # entering a class: the multiclass proficiencies, order, level 1 things
    if ctx.entering:
        gain = spec.MULTICLASS_GAINS[klass.id]
        for category in gain.armor:
            _set_proficiency(character, "armor", category)
        for category in gain.weapons:
            _set_proficiency(character, "weapon", category)
        for tool_id in gain.tools:
            _set_proficiency(character, "tool", tool_id)
        for skill_id in ctx.get("lu.entry_skills"):
            _set_proficiency(character, "skill", skill_id)
        if ctx.one("lu.entry_tool"):
            _set_proficiency(character, "tool", ctx.one("lu.entry_tool"))
        for language_id in (*class_spec.languages, ctx.one("lu.language")):
            if language_id and Language.objects.filter(id=language_id).exists():
                CharacterLanguage.objects.get_or_create(
                    character=character, language_id=language_id
                )
        if ctx.one("lu.order"):
            order = next(
                o
                for o in class_spec.orders
                if o.feature.lower().replace(" ", "-") == ctx.one("lu.order")
            )
            for category in order.weapon_categories:
                _set_proficiency(character, "weapon", category)
            for category in order.armor_categories:
                _set_proficiency(character, "armor", category)
            CharacterChoice.objects.update_or_create(
                character=character,
                key=f"levelup.order.{klass.id}",
                defaults={"value": ctx.one("lu.order")},
            )
        for spell_key in class_spec.always_prepared:
            _add_spell(
                character,
                spell_key,
                klass.id,
                f"class:{klass.id}",
                prepared=True,
                always_prepared=True,
            )

    # class choices
    for skill_id in ctx.get("lu.expertise"):
        _set_proficiency(character, "skill", skill_id, "expertise")
    for skill_id in ctx.get("lu.skills"):
        _set_proficiency(character, "skill", skill_id)
    if ctx.one("lu.tool"):
        _set_proficiency(character, "tool", ctx.one("lu.tool"))
    for language_id in ctx.get("lu.languages"):
        CharacterLanguage.objects.get_or_create(character=character, language_id=language_id)
    if ctx.one("lu.style"):
        style = Feat.objects.get(id=ctx.one("lu.style"))
        _add_feat(character, style, total, "class")
        _apply_feat_picks(ctx, style, "lu.style", total)
    if ctx.get("lu.weapon_mastery"):
        CharacterChoice.objects.update_or_create(
            character=character,
            key="class.weapon_mastery",
            defaults={"value": [*_known_masteries(character), *ctx.get("lu.weapon_mastery")]},
        )
    for key, out_key, in_key in (
        ("lu.metamagic", "lu.metamagic_out", "lu.metamagic_in"),
        ("lu.maneuvers", "lu.maneuver_out", "lu.maneuver_in"),
        ("lu.invocations", "lu.invocation_out", "lu.invocation_in"),
    ):
        for option_id in ctx.get(key):
            CharacterOptionalFeature.objects.get_or_create(
                character=character,
                optional_feature_id=option_id,
                defaults={"granted_at_level": new},
            )
        if ctx.one(out_key) and ctx.one(in_key):
            CharacterOptionalFeature.objects.filter(
                character=character, optional_feature_id=ctx.one(out_key)
            ).delete()
            CharacterOptionalFeature.objects.get_or_create(
                character=character,
                optional_feature_id=ctx.one(in_key),
                defaults={"granted_at_level": new},
            )

    # spells
    source = f"class:{klass.id}"
    for spell_key in ctx.get("lu.cantrips"):
        _add_spell(character, spell_key, klass.id, source, prepared=True)
    book = set(ctx.get("lu.spellbook"))
    prepared = set(ctx.get("lu.spells"))
    for spell_key in book:
        _add_spell(
            character,
            spell_key,
            klass.id,
            source,
            prepared=spell_key in prepared,
            in_spellbook=True,
        )
    for spell_key in prepared - book:
        if klass.id == "wizard":
            CharacterSpell.objects.filter(character=character, spell_id=spell_key).update(
                prepared=True
            )
        else:
            _add_spell(character, spell_key, klass.id, source, prepared=True)
    if ctx.one("lu.spell_out") and ctx.one("lu.spell_in"):
        CharacterSpell.objects.filter(
            character=character, spell_id=ctx.one("lu.spell_out")
        ).delete()
        _add_spell(character, ctx.one("lu.spell_in"), klass.id, source, prepared=True)
    if ctx.one("lu.arcanum"):
        _add_spell(
            character,
            ctx.one("lu.arcanum"),
            klass.id,
            source,
            prepared=True,
            always_prepared=True,
            free_cast=True,
        )

    # resources (after the class row exists, and with the new scores)
    ctx.rows[klass.id] = row
    _update_resources(ctx, new, subclass, mods)
    feature_resources.refresh(character)
    return plan_

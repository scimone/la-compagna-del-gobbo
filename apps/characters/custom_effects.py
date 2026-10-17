"""Effects the player defines on their own custom items and custom features.

An effect is `{"target": <key>, "value": <int>}`. `value` is a bonus (or penalty), except for the
"flag" targets (proficiency, expertise), where it is always 1, and `ability_min:*`, where it is
the score the ability is raised to if it is lower (Gauntlets of Ogre Power: Strength 19).

Targets, by key:

- `ac`, `speed`, `initiative`, `passive_perception`, `attack` (every attack roll), `damage`
  (every damage roll), `spell_dc`, `spell_attack`, `save_all`, `skill_all`;
- `weapon_attack`, `weapon_damage` - only the weapon that carries the effect (a +1 sword);
- `ability:<id>` (bonus to the score), `ability_min:<id>`, `save:<id>`, `skill:<id>`;
- `prof_save:<id>`, `prof_skill:<id>`, `expert_skill:<id>` - flags.

`clean()` validates what a form posts (a JSON list); `collect()` lists the effects in force for a
character - those of the custom features, and of the worn custom items - for
`builder.derived_stats` to apply.
"""

import json

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.rules.models import Ability, Skill

MAX_EFFECTS = 20
MAX_BONUS = 100
SCORE_MAX = 30

#: Plain targets, in the order the editor lists them: `(key, label)`.
SIMPLE_TARGETS = (
    ("ac", gettext_lazy("Armor Class")),
    ("speed", gettext_lazy("Speed (ft)")),
    ("initiative", gettext_lazy("Initiative")),
    ("passive_perception", gettext_lazy("Passive Perception")),
    ("attack", gettext_lazy("All attack rolls")),
    ("damage", gettext_lazy("All damage rolls")),
    ("spell_dc", gettext_lazy("Spell save DC")),
    ("spell_attack", gettext_lazy("Spell attack bonus")),
    ("save_all", gettext_lazy("All saving throws")),
    ("skill_all", gettext_lazy("All skills")),
)
WEAPON_TARGETS = (
    ("weapon_attack", gettext_lazy("Attack rolls with this weapon")),
    ("weapon_damage", gettext_lazy("Damage rolls with this weapon")),
)
#: `prefix -> flag?` for the targets that name an ability or a skill.
PARAMETRIC = {
    "ability": False,
    "ability_min": False,
    "save": False,
    "skill": False,
    "prof_save": True,
    "prof_skill": True,
    "expert_skill": True,
}
_ON_ABILITY = ("ability", "ability_min", "save", "prof_save")


def _ids(model) -> set[str]:
    return set(model.objects.values_list("pk", flat=True))


def is_flag(target: str) -> bool:
    return PARAMETRIC.get(target.partition(":")[0], False)


def valid_target(target: str, abilities: set[str], skills: set[str]) -> bool:
    if target in dict(SIMPLE_TARGETS) or target in dict(WEAPON_TARGETS):
        return True
    prefix, _sep, ref = target.partition(":")
    if prefix not in PARAMETRIC:
        return False
    return ref in (abilities if prefix in _ON_ABILITY else skills)


def clean(raw, *, weapon: bool = False) -> list[dict]:
    """The validated effects from what a form posts: a JSON list, or an already-parsed one.
    `ValueError` for anything that is not an effect. The two `weapon_*` targets only mean
    something on a weapon, so anywhere else they are dropped."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("effects are not valid JSON") from None
    if not isinstance(raw, list) or len(raw) > MAX_EFFECTS:
        raise ValueError("too many effects")
    abilities, skills = _ids(Ability), _ids(Skill)
    result = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("an effect must be an object")
        target = str(entry.get("target", ""))
        if not valid_target(target, abilities, skills):
            raise ValueError(f"unknown effect target {target!r}")
        if target in dict(WEAPON_TARGETS) and not weapon:
            continue
        try:
            value = 1 if is_flag(target) else int(entry.get("value"))
        except (TypeError, ValueError):
            raise ValueError(f"effect {target!r} needs a number") from None
        low = 1 if target.startswith("ability_min:") else -MAX_BONUS
        high = SCORE_MAX if target.startswith("ability_min:") else MAX_BONUS
        if not low <= value <= high:
            raise ValueError(f"effect {target!r} is out of range")
        effect = {"target": target, "value": value}
        if effect not in result:
            result.append(effect)
    return result


def target_label(target: str, names: dict[str, str]) -> str:
    """A target in words (`names`: ability and skill ids to their names)."""
    for key, label in (*SIMPLE_TARGETS, *WEAPON_TARGETS):
        if key == target:
            return str(label)
    prefix, _sep, ref = target.partition(":")
    name = names.get(ref, ref)
    return {
        "ability": _("%(name)s score"),
        "ability_min": _("%(name)s score"),
        "save": _("%(name)s saving throws"),
        "skill": _("%(name)s checks"),
        "prof_save": _("Proficiency: %(name)s saving throws"),
        "prof_skill": _("Proficiency: %(name)s"),
        "expert_skill": _("Expertise: %(name)s"),
    }[prefix] % {"name": name}


def describe(effect: dict, names: dict[str, str]) -> str:
    """One effect as a line: "+2 Armor Class", "Proficiency: Stealth"."""
    target, value = effect["target"], effect["value"]
    label = target_label(target, names)
    if is_flag(target):
        return label
    if target.startswith("ability_min:"):
        return _("%(label)s at least %(value)s") % {"label": label, "value": value}
    return f"{value:+d} {label}"


def names() -> dict[str, str]:
    """Ability and skill ids to their (translated) names."""
    return {
        **{a.pk: a.name for a in Ability.objects.all()},
        **{s.pk: s.name for s in Skill.objects.all()},
    }


def editor_options() -> list[dict]:
    """What the effects editor offers, as groups `{"label", "weapon", "options": [{"key",
    "label", "flag"}]}`; the group of a weapon's own rolls (`weapon`) is shown on weapons only."""
    order = ("str", "dex", "con", "int", "wis", "cha")
    abilities = sorted(
        ((a.pk, a.name) for a in Ability.objects.all()),
        key=lambda a: order.index(a[0]) if a[0] in order else len(order),
    )
    skills = [(s.pk, s.name) for s in Skill.objects.order_by("name")]

    def simple(*keys):
        labels = dict(SIMPLE_TARGETS) | dict(WEAPON_TARGETS)
        return [{"key": k, "label": labels[k], "flag": False} for k in keys]

    def per(prefix, pairs, label):
        return [
            {"key": f"{prefix}:{ref}", "label": label % {"name": name}, "flag": PARAMETRIC[prefix]}
            for ref, name in pairs
        ]

    groups = [
        (
            _("Combat and movement"),
            False,
            simple("ac", "speed", "initiative", "attack", "damage", "spell_dc", "spell_attack"),
        ),
        (_("This weapon"), True, simple("weapon_attack", "weapon_damage")),
        (
            _("Ability scores"),
            False,
            per("ability", abilities, _("%(name)s score (bonus)"))
            + per("ability_min", abilities, _("%(name)s score (at least)")),
        ),
        (
            _("Saving throws"),
            False,
            simple("save_all")
            + per("save", abilities, _("%(name)s saving throws"))
            + per("prof_save", abilities, _("Proficiency: %(name)s saving throws")),
        ),
        (
            _("Skills"),
            False,
            simple("passive_perception", "skill_all")
            + per("skill", skills, _("%(name)s checks"))
            + per("prof_skill", skills, _("Proficiency: %(name)s"))
            + per("expert_skill", skills, _("Expertise: %(name)s")),
        ),
    ]
    return [
        {
            "label": str(label),
            "weapon": weapon,
            "options": [{**o, "label": str(o["label"])} for o in options],
        }
        for label, weapon, options in groups
    ]


def collect(character) -> list[tuple[dict, str]]:
    """Every effect in force for `character`, as `(effect, owner)`: the custom features', and the
    worn custom items' (`owner` is `"custom:<item pk>"` for an item, `""` for a feature)."""
    found = [(e, "") for f in character.custom_features.all() for e in f.effects]
    for item in character.custom_items.filter(equipped=True):
        found += [(e, f"custom:{item.pk}") for e in item.effects]
    return found

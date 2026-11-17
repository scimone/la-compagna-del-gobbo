"""A creature's stat block as the facts + rendered sections every description in the app uses
(`_describe.html`, the World's detail page): the Wild Shape picker, the sheet's "Wild Shape:
<beast>" cards and `/world/creatures/<id>/` all show the same thing."""

from django.utils.translation import gettext as _

from apps.frontend.entries_render import render_entries
from apps.frontend.units import metricize_text

_ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{abs(n)}"


def type_line(creature) -> str:
    kind = f"{creature.type} ({creature.subtype})" if creature.subtype else creature.type
    return f"{creature.size} {kind}, {creature.alignment}".strip(", ")


def line(creature) -> str:
    """The one line under a card's name: `Medium · CR 1/4 · 40 ft.`."""
    return " · ".join(
        [creature.size, f"{_('CR')} {creature.cr}", metricize_text(creature.speed_text)]
    )


def facts_and_sections(creature) -> tuple[list[tuple[str, str]], list]:
    facts = [
        (_("Type"), type_line(creature)),
        (_("Armor Class"), creature.ac),
        (
            _("Initiative"),
            f"{_signed(creature.initiative_modifier)} ({creature.initiative_score})",
        ),
        (_("Hit Points"), f"{creature.hp_average} ({creature.hp_formula})"),
        (_("Speed"), metricize_text(creature.speed_text)),
    ]
    for label, value in (
        (_("Skills"), ", ".join(f"{k} {_signed(v)}" for k, v in (creature.skills or {}).items())),
        (_("Vulnerabilities"), creature.vulnerabilities),
        (_("Resistances"), creature.resistances),
        (_("Immunities"), creature.immunities),
        (_("Senses"), metricize_text(creature.senses)),
        (_("Languages"), creature.languages),
        (_("Gear"), creature.gear),
    ):
        if value:
            facts.append((label, value))
    facts.append(
        (
            _("Challenge"),
            f"{creature.cr} (XP {creature.xp:,}; {_('PB')} {_signed(creature.proficiency_bonus)})",
        )
    )
    abilities = creature.abilities or {}
    table = {
        "type": "table",
        "colLabels": [a.upper() for a in _ABILITIES],
        "rows": [
            [
                f"{abilities[a]['score']} ({_signed(abilities[a]['mod'])})"
                for a in _ABILITIES
                if a in abilities
            ]
        ],
    }
    sections = [render_entries([table])]
    for heading, entries in (
        (_("Traits"), creature.traits),
        (_("Actions"), creature.actions),
        (_("Bonus Actions"), creature.bonus_actions),
        (_("Reactions"), creature.reactions),
    ):
        if entries:
            sections.append(
                render_entries([{"type": "entries", "name": heading, "entries": entries}])
            )
    return facts, sections


def actions_text(creature) -> list[tuple[str, str]]:
    """`(name, text)` for the stat block's traits, actions, bonus actions and reactions, plain."""
    return [
        (e["name"], metricize_text(" ".join(e.get("entries", []))))
        for group in (creature.traits, creature.actions, creature.bonus_actions, creature.reactions)
        for e in group
    ]

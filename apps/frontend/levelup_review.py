"""The level-up's review step: what this level changes, as blocks the template lays out.

Shaping only - the rules are `builder.services.progression`. A block is one thing that changes
(hit points, new features, the spells added, a spell swapped, the feat ...) with the step it comes
from, so the page can offer "Edit" next to it and say where a choice is still missing.
"""

from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.builder import tables
from apps.frontend.character_sheet import _feature_row
from apps.frontend.entries_render import _format_table_cell
from apps.rules.models import Ability, ClassLevel

#: Sections whose two pickers are "this out, that in".
_SWAP_SECTIONS = ("spell_swap", "subclass_swap")
_CARD_URLS = {
    "spell": "world-spell-detail",
    "feat": "world-feat-detail",
    "creature": "world-creature-detail",
}


def _rows(picker) -> list[dict]:
    """The picks of one picker as list rows: catalog cards where the picker has them, else names."""
    if getattr(picker, "cards", None) is not None:
        url_name = _CARD_URLS.get(picker.kind)
        return [
            {
                "name": c["name"],
                "detail": c["detail"],
                "image": c["image"],
                "url": reverse(url_name, args=[c["id"]]) if url_name else "",
            }
            for c in picker.cards
            if c["checked"]
        ]
    return [{"name": n} for i, n in picker.candidates if i in picker.selected]


def _missing(picker) -> int:
    """How many required picks the picker still lacks."""
    if picker.optional:
        return 0
    need = min(picker.count, len(picker.candidates))
    return max(0, need - len(picker.selected))


def _hp_block(plan) -> dict:
    hp = plan.hp
    gain = hp["gain"] + hp["retro"]
    how = (
        _("rolled %(n)d") % {"n": hp["roll"]}
        if hp["mode"] == "roll" and hp["roll"]
        else _("average of the %(die)s") % {"die": hp["die"]}
    )
    return {
        "key": "hp",
        "title": _("Hit points"),
        "step": 0,
        "groups": [
            {"label": "", "rows": [{"name": _("+%(n)d hit points") % {"n": gain}, "detail": how}]}
        ],
    }


def _effects(plan) -> list[dict]:
    """What the level raises without any choice: proficiency bonus, hit dice, the class table's
    new numbers (spell slots, cantrips, prepared spells, Rages, Martial Arts die ...) as
    `{name, old, new}`. Only what actually changes; spell slots only for a single casting class
    (a multiclass character's slots come from the combined table)."""
    klass = plan.klass
    effects = []

    def add(name, old, new):
        if old != new:
            effects.append({"name": name, "old": old if old != "" else "—", "new": new})

    add(
        _("Proficiency bonus"),
        f"+{tables.proficiency_bonus(plan.total_after - 1)}",
        f"+{tables.proficiency_bonus(plan.total_after)}",
    )
    effects.append(
        {
            "name": _("Hit Dice"),
            "old": f"{plan.old_level}{klass.hit_die}" if plan.old_level else "—",
            "new": f"{plan.new_level}{klass.hit_die}",
        }
    )
    rows = {
        r.level: r
        for r in ClassLevel.objects.filter(klass=klass, level__in=(plan.old_level, plan.new_level))
    }
    old, new = rows.get(plan.old_level), rows.get(plan.new_level)
    if not new:
        return effects
    other_casters = (
        plan.character.classes.exclude(klass=klass)
        .filter(klass__spellcasting_ability__isnull=False)
        .exists()
    )
    if new.spell_slots and not other_casters:
        before = old.spell_slots if old else []
        for level, count in enumerate(new.spell_slots, start=1):
            was = before[level - 1] if level <= len(before) else 0
            if count != was:
                add(_("Level %(n)d spell slots") % {"n": level}, str(was), str(count))
    add(_("Cantrips"), str(old.cantrips_known or "") if old else "", str(new.cantrips_known or ""))
    add(
        _("Prepared spells"),
        str(old.spells_known_or_prepared or "") if old else "",
        str(new.spells_known_or_prepared or ""),
    )
    for column, value in new.columns.items():
        was = _format_table_cell(old.columns[column]) if old and column in old.columns else ""
        add(_(column), was, _format_table_cell(value))
    return effects


def build(plan, steps) -> dict:
    """`{"blocks": [...], "todo": [...]}` for `plan`; `steps` are the page's steps, in order."""
    blocks = [_hp_block(plan)]
    if effects := _effects(plan):
        blocks.append(
            {"key": "effects", "title": _("Also improves"), "step": None, "effects": effects}
        )
    todo = []
    if plan.features:
        blocks.append(
            {
                "key": "features",
                "title": _("New features"),
                "step": None,
                "groups": [{"label": "", "rows": [_feature_row(f) for f in plan.features]}],
            }
        )
    deltas = plan.extra.get("deltas") or {}
    abilities = {a.id: a.name for a in Ability.objects.all()} if deltas else {}
    for index, section in enumerate(steps):
        if section.key == "hp":
            continue
        block = {"key": section.key, "title": section.title, "step": index, "groups": []}
        pickers = section.pickers
        if section.key in _SWAP_SECTIONS and len(pickers) == 2:
            out, new = (_rows(p) for p in pickers)
            if out and new:
                block["swap"] = {"old": out[0], "new": new[0]}
            elif out or new:
                block["incomplete"] = _("Pick the spell to put in its place too.")
                todo.append(index)
        else:
            for picker in pickers:
                if rows := _rows(picker):
                    block["groups"].append({"label": picker.label, "rows": rows})
            if section.key == "feat" and deltas:
                block["groups"].append(
                    {
                        "label": "",
                        "rows": [
                            {"name": f"{abilities.get(a, a)} +{n}", "detail": ""}
                            for a, n in deltas.items()
                        ],
                    }
                )
            if left := sum(_missing(p) for p in pickers):
                block["incomplete"] = ngettext(
                    "%(n)d choice still to make.", "%(n)d choices still to make.", left
                ) % {"n": left}
                todo.append(index)
        if block["groups"] or block.get("swap") or block.get("incomplete"):
            blocks.append(block)
    return {"blocks": blocks, "todo": todo, "next_todo": todo[0] if todo else None}

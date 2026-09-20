"""Spell lookups (list_spells, get_spell)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Spell


def list_spells(klass: str | None = None, level: int | None = None):
    qs = Spell.objects.all()
    if klass:
        qs = qs.filter(classes__contains=[klass])
    if level is not None:
        qs = qs.filter(level=level)
    return qs


def get_spell(spell_id: str) -> Spell:
    return get_object_or_404(Spell, pk=spell_id)


def list_classes() -> list[str]:
    """Every distinct class name appearing in some `Spell.classes`, for the World > Spells
    filter dropdown - not `rules.Class.objects.values_list("name")`, since `classes` is frozen
    `db_old` data (see `Spell`'s docstring) kept separate from `Class` on principle, even though
    every name in it happens to match a real `Class` row today ("Artificer", the one name that
    didn't, is dropped at import time).
    """
    return sorted({c for spell in Spell.objects.all() for c in (spell.classes or [])})


def list_schools() -> list[str]:
    """Every distinct `Spell.school` value, for the World > Spells school checklist filter."""
    return sorted({school for school in Spell.objects.values_list("school", flat=True)})


def range_label(range_data: dict | None) -> str:
    """Formats a `Spell.range` JSON (see `Spell`'s docstring for the source shape) the way a
    spell's detail page shows it - `Self`/`Touch`/`Sight`/`Unlimited` for a distance with no
    numeric amount, `<amount> <unit>` (`120 feet`, `1 mile`) for one with, and the capitalized
    `type` when there's no distance at all. An area-effect shape (`emanation`, `cone`, ...) is
    labeled by its size alone, same as a plain `point` range of that size.
    """
    if not range_data:
        return ""
    distance = range_data.get("distance") or {}
    amount = distance.get("amount")
    if amount is not None:
        unit = distance.get("type", "")
        if amount == 1 and unit.endswith("s"):
            unit = unit[:-1]
        return f"{amount} {unit}".strip()
    if distance.get("type"):
        return distance["type"].capitalize()
    return (range_data.get("type") or "").capitalize()


def range_kind(spell: Spell) -> str:
    """A spell's range checklist-facet value - just its `range_label()`, so the filter options
    read exactly like the range shown on the spell itself.
    """
    return range_label(spell.range)


# Non-numeric range labels, then numeric ones by unit (feet before miles), then `Unlimited`.
_RANGE_LABEL_ORDER = ["Self", "Touch", "Sight"]
_RANGE_UNIT_ORDER = ["feet", "foot", "mile", "miles"]


def _range_sort_key(label: str) -> tuple:
    amount, _, unit = label.partition(" ")
    if amount.isdigit() and unit in _RANGE_UNIT_ORDER:
        return (1, _RANGE_UNIT_ORDER.index(unit) // 2, int(amount), label)
    if label in _RANGE_LABEL_ORDER:
        return (0, _RANGE_LABEL_ORDER.index(label), 0, label)
    return (2, 0, 0, label)


def list_range_kinds() -> list[str]:
    """Every distinct `range_kind()` label actually present, for the World > Spells range
    checklist filter, ordered by actual distance (`Self`, `Touch`, `5 feet`, ..., `1 mile`, ...,
    `Unlimited`) rather than alphabetically.
    """
    kinds = {range_kind(spell) for spell in Spell.objects.all()}
    return sorted(kinds - {""}, key=_range_sort_key)


# Every `(number, unit)` pair `Spell.casting_time` entries actually use, in the order they
# should be offered as checklist options - not sorted alphabetically, since e.g. "10 Minutes"
# would then land between "1 Hour" and "1 Minute".
_CASTING_TIME_ORDER = [
    (1, "action"),
    (1, "bonus"),
    (1, "reaction"),
    (1, "minute"),
    (10, "minute"),
    (1, "hour"),
    (8, "hour"),
    (12, "hour"),
    (24, "hour"),
]
_CASTING_TIME_LABELS = {
    (1, "action"): "1 Action",
    (1, "bonus"): "1 Bonus Action",
    (1, "reaction"): "1 Reaction",
    (1, "minute"): "1 Minute",
    (10, "minute"): "10 Minutes",
    (1, "hour"): "1 Hour",
    (8, "hour"): "8 Hours",
    (12, "hour"): "12 Hours",
    (24, "hour"): "24 Hours",
}


def casting_time_keys(spell: Spell) -> list[str]:
    """Every `"<number>|<unit>"` key `spell.casting_time` maps to - a spell can offer more than
    one (e.g. a reaction alternative to its normal action cost), so this is a list, checked
    against a checklist filter's selection with a set intersection rather than a single equality.
    """
    return [f"{entry.get('number')}|{entry.get('unit')}" for entry in spell.casting_time or []]


def list_casting_times() -> list[tuple[str, str]]:
    """`[(key, label), ...]` for every casting time actually present, for the World > Spells
    casting time checklist filter - `key` matches what `casting_time_keys()` produces.
    """
    present = {key for spell in Spell.objects.all() for key in casting_time_keys(spell)}
    return [
        (f"{number}|{unit}", _CASTING_TIME_LABELS[(number, unit)])
        for number, unit in _CASTING_TIME_ORDER
        if f"{number}|{unit}" in present
    ]

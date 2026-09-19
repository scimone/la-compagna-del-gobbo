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
    `db_old` data that still names classes (e.g. Artificer) this app's own `Class` table doesn't
    have a row for (see `Spell`'s docstring) - a dropdown sourced from `Class` would silently
    drop spells for one of those.
    """
    return sorted({c for spell in Spell.objects.all() for c in (spell.classes or [])})


def list_schools() -> list[str]:
    """Every distinct `Spell.school` value, for the World > Spells school checklist filter."""
    return sorted({school for school in Spell.objects.values_list("school", flat=True)})


def range_kind(spell: Spell) -> str:
    """Buckets a spell's `range` JSON (see `Spell`'s docstring for the source shape) into a
    short, filterable label: `Self`/`Touch`/`Sight`/`Unlimited` for a `type: "point"` entry whose
    `distance.type` names one of those (no numeric amount to speak of), `Ranged` for any other
    point distance (a `feet`/`miles` amount - the exact number is too granular a checklist
    facet), and the raw area-effect shape (`Cone`/`Cube`/`Emanation`/`Line`/`Sphere`) for every
    non-`point` type.
    """
    range_data = spell.range or {}
    range_type = range_data.get("type")
    if range_type == "point":
        distance_type = (range_data.get("distance") or {}).get("type")
        return {
            "self": "Self",
            "touch": "Touch",
            "sight": "Sight",
            "unlimited": "Unlimited",
        }.get(distance_type, "Ranged")
    return (range_type or "").capitalize()


def list_range_kinds() -> list[str]:
    """Every distinct `range_kind()` bucket actually present, for the World > Spells range
    checklist filter.
    """
    return sorted({range_kind(spell) for spell in Spell.objects.all()})


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

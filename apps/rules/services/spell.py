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

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

"""Proficiency lookups (list_proficiencies)."""

from apps.rules.models import Proficiency


def list_proficiencies():
    return Proficiency.objects.all()

"""Creature lookups (get_creature, list_creatures)."""

from django.http import Http404

from apps.rules.models import Creature


def get_creature(creature_id: str) -> Creature:
    try:
        return Creature.objects.get(pk=creature_id)
    except Creature.DoesNotExist:
        raise Http404 from None


def list_creatures():
    return Creature.objects.all()

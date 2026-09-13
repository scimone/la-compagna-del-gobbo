"""Subclass lookups (list_subclasses, get_subclass)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Subclass, SubclassLevel


def list_subclasses():
    return Subclass.objects.all()


def get_subclass(subclass_id: int) -> Subclass:
    return get_object_or_404(Subclass, pk=subclass_id)


def list_subclass_levels(subclass_id: int):
    get_subclass(subclass_id)
    return SubclassLevel.objects.filter(subclass_id=subclass_id)

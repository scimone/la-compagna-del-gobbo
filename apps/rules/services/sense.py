"""Sense lookups (list_senses)."""

from apps.rules.models import Sense


def list_senses():
    return Sense.objects.all()

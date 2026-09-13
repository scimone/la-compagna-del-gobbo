"""Species lookups (list_species, get_species)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Species


def list_species():
    return Species.objects.all()


def get_species(species_id: str) -> Species:
    return get_object_or_404(Species, pk=species_id)

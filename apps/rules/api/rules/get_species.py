"""Placeholder for GET /species/{species_id}."""

from apps.rules.api.rules import router


@router.get("/species/{species_id}")
def get_species(request, species_id: int):
    """Retrieve a species. TODO: implement via services."""

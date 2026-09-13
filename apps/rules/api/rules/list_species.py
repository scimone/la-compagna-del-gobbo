"""Placeholder for GET /species."""

from apps.rules.api.rules import router


@router.get("/species")
def list_species(request):
    """List all species. TODO: implement via services."""

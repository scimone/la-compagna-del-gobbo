"""Placeholder for GET /spells."""

from apps.rules.api.rules import router


@router.get("/spells")
def list_spells(request):
    """List all spells. TODO: implement via services."""

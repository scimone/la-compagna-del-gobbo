"""Placeholder for GET /proficiencies."""

from apps.rules.api.rules import router


@router.get("/proficiencies")
def list_proficiencies(request):
    """List all proficiency categories. TODO: implement via services."""

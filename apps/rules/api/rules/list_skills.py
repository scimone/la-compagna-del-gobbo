"""Placeholder for GET /skills."""

from apps.rules.api.rules import router


@router.get("/skills")
def list_skills(request):
    """List all skills. TODO: implement via services."""

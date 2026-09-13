"""Placeholder for GET /tools."""

from apps.rules.api.rules import router


@router.get("/tools")
def list_tools(request):
    """List all tools. TODO: implement via services."""

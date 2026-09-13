"""Placeholder for GET /rules."""

from apps.rules.api.rules import router


@router.get("/rules")
def list_rules(request):
    """List all named rules. TODO: implement via services."""

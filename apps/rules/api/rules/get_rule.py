"""Placeholder for GET /rules/{rule_key}."""

from apps.rules.api.rules import router


@router.get("/rules/{rule_key}")
def get_rule(request, rule_key: str):
    """Retrieve a named rule by key. TODO: implement via services."""

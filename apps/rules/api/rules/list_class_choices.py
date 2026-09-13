"""Placeholder for GET /classes/{class_id}/choices."""

from apps.rules.api.rules import router


@router.get("/classes/{class_id}/choices")
def list_class_choices(request, class_id: str):
    """List the parsed choice definitions for a class. TODO: implement via services."""

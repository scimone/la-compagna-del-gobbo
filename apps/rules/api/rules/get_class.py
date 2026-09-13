"""Placeholder for GET /classes/{class_id}."""

from apps.rules.api.rules import router


@router.get("/classes/{class_id}")
def get_class(request, class_id: str):
    """Retrieve a class. TODO: implement via services."""

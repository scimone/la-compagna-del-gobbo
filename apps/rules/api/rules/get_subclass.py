"""Placeholder for GET /subclasses/{subclass_id}."""

from apps.rules.api.rules import router


@router.get("/subclasses/{subclass_id}")
def get_subclass(request, subclass_id: int):
    """Retrieve a subclass. TODO: implement via services."""

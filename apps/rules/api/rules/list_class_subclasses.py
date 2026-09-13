"""Placeholder for GET /classes/{class_id}/subclasses."""

from apps.rules.api.rules import router


@router.get("/classes/{class_id}/subclasses")
def list_class_subclasses(request, class_id: int):
    """List the subclasses available for a class. TODO: implement via services."""

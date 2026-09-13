"""Placeholder for GET /equipment/{equipment_id}."""

from apps.rules.api.rules import router


@router.get("/equipment/{equipment_id}")
def get_equipment(request, equipment_id: int):
    """Retrieve an equipment item. TODO: implement via services."""

from apps.rules.api.rules import router
from apps.rules.schemas import EquipmentSchema
from apps.rules.services import equipment


@router.get("/equipment", response=list[EquipmentSchema])
def list_equipment(request, category: str | None = None):
    return equipment.list_equipment(category=category)

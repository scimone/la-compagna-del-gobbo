from apps.rules.api.rules import router
from apps.rules.schemas import EquipmentSchema
from apps.rules.services import equipment


@router.get("/equipment/{equipment_id}", response=EquipmentSchema)
def get_equipment(request, equipment_id: str):
    return equipment.get_equipment(equipment_id)

from apps.rules.api.rules import router
from apps.rules.schemas import EquipmentPropertySchema
from apps.rules.services import equipment


@router.get("/equipment-properties", response=list[EquipmentPropertySchema])
def list_equipment_properties(request):
    return equipment.list_equipment_properties()

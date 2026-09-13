from apps.characters.api.inventory import router
from apps.characters.schemas import CharacterInventoryItemSchema
from apps.characters.services import inventory


@router.get("/{character_id}/inventory", response=list[CharacterInventoryItemSchema])
def list_inventory(request, character_id: int):
    return inventory.list_inventory(character_id)

from apps.characters.api.inventory import router
from apps.characters.schemas import CharacterInventoryItemSchema
from apps.characters.services import inventory


@router.post("/{character_id}/inventory/{item_id}/unequip", response=CharacterInventoryItemSchema)
def unequip_inventory_item(request, character_id: int, item_id: int):
    return inventory.unequip_inventory_item(character_id, item_id)

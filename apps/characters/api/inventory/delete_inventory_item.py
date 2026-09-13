from apps.characters.api.inventory import router
from apps.characters.services import inventory


@router.delete("/{character_id}/inventory/{item_id}")
def delete_inventory_item(request, character_id: int, item_id: int):
    inventory.delete_inventory_item(character_id, item_id)
    return {"success": True}

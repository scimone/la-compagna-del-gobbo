from django.db import models


class CharacterInventoryItem(models.Model):
    """An Equipment item (or stack of identical items) owned by a Character.

    No uniqueness constraint on (character, equipment): the same item can be owned as separate
    stacks in different states (e.g. one equipped longsword and one spare in a pack), so
    `quantity` covers identical-and-together stacking, while distinct rows cover
    identical-but-separate items.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="inventory_items", on_delete=models.CASCADE
    )
    equipment = models.ForeignKey("rules.Equipment", on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveSmallIntegerField(default=1)
    equipped = models.BooleanField(default=False)
    attuned = models.BooleanField(default=False)
    notes = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["character", "equipment"]

    def __str__(self) -> str:
        return f"{self.character}: {self.equipment.name} x{self.quantity}"

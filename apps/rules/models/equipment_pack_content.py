from django.db import models


class EquipmentPackContent(models.Model):
    """One item stack inside an equipment pack (e.g. Burglar's Pack contains a Backpack, 10
    Candles, ...), sourced from `db/equipment.json` `item.packContents`.

    Wholly new: the old format never resolved pack contents to real `Equipment` rows. Bare string
    entries in the source (`"backpack|xphb"`) default to `quantity=1`; `{"item": ..., "quantity":
    N}` entries carry their own count.
    """

    pack = models.ForeignKey(
        "rules.Equipment", related_name="pack_content_rows", on_delete=models.CASCADE
    )
    item = models.ForeignKey("rules.Equipment", related_name="+", on_delete=models.CASCADE)
    quantity = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["pack", "item"]
        constraints = [
            models.UniqueConstraint(fields=["pack", "item"], name="unique_pack_item"),
        ]

    def __str__(self) -> str:
        return f"{self.pack.name}: {self.quantity}x {self.item.name}"

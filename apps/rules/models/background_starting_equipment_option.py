from django.db import models


class BackgroundStartingEquipmentOption(models.Model):
    """One item (or gold grant) in a Background's "choose A or B" starting-equipment list,
    sourced from `db/backgrounds.json`'s `startingEquipment`.

    Wholly new - the old format had this data only as unparsed prose. `item` is null for a plain
    gold-value row (option "B" is typically just a lump currency grant, e.g. 50 GP, with no item).
    """

    background = models.ForeignKey(
        "rules.Background", related_name="starting_equipment_options", on_delete=models.CASCADE
    )
    option = models.CharField(max_length=1)
    item = models.ForeignKey(
        "rules.Equipment", related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    quantity = models.PositiveSmallIntegerField(default=1)
    gold_value = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["background", "option"]

    def __str__(self) -> str:
        if self.item_id:
            return f"{self.background.name} ({self.option}): {self.quantity}x {self.item_id}"
        return f"{self.background.name} ({self.option}): {self.gold_value} cp"

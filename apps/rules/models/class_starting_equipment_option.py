from django.db import models


class ClassStartingEquipmentOption(models.Model):
    """One item (or gold grant) in a Class's "choose A, B, or C" starting-equipment list, sourced
    from `db/classes.json`'s `class.startingEquipment`.

    Wholly new - the old format had this data only as unparsed prose. Same shape as
    `BackgroundStartingEquipmentOption` (a class and a background each independently offer a
    starting-equipment choice; `characters`/`builder` combine both when a character picks both).
    `item` is null for a plain gold-value row (e.g. option "C" is typically just a lump currency
    grant with no item).
    """

    klass = models.ForeignKey(
        "rules.Class", related_name="starting_equipment_options", on_delete=models.CASCADE
    )
    option = models.CharField(max_length=1)
    item = models.ForeignKey(
        "rules.Equipment", related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    quantity = models.PositiveSmallIntegerField(default=1)
    gold_value = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["klass", "option"]

    def __str__(self) -> str:
        if self.item_id:
            return f"{self.klass.name} ({self.option}): {self.quantity}x {self.item_id}"
        return f"{self.klass.name} ({self.option}): {self.gold_value} cp"

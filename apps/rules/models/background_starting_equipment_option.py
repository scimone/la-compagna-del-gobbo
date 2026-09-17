from django.db import models


class BackgroundStartingEquipmentOption(models.Model):
    """One item (or gold grant) in a Background's "choose A or B" starting-equipment list,
    sourced from `db/backgrounds.json`'s `startingEquipment`.

    Wholly new - the old format had this data only as unparsed prose. `item` is null for a plain
    gold-value row (option "B" is typically just a lump currency grant, e.g. 50 GP, with no item)
    - or for a "pick any X" grant that names an `EquipmentGroup` instead of one concrete item
    (e.g. Acolyte's "Holy Symbol" - not itself a real `Equipment` row, since Amulet/Emblem/
    Reliquary are the actual choices; verified this is the only shape that fails to resolve
    against `Equipment`, across every Background/Class starting-equipment reference in `db/`).
    Exactly one of `item`/`group`/`gold_value` is set per row.
    """

    background = models.ForeignKey(
        "rules.Background", related_name="starting_equipment_options", on_delete=models.CASCADE
    )
    option = models.CharField(max_length=1)
    item = models.ForeignKey(
        "rules.Equipment", related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    group = models.ForeignKey(
        "rules.EquipmentGroup", related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    quantity = models.PositiveSmallIntegerField(default=1)
    gold_value = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["background", "option"]

    def __str__(self) -> str:
        if self.item_id:
            return f"{self.background.name} ({self.option}): {self.quantity}x {self.item_id}"
        if self.group_id:
            return f"{self.background.name} ({self.option}): any {self.group_id}"
        return f"{self.background.name} ({self.option}): {self.gold_value} cp"

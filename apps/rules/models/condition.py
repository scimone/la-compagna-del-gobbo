from django.db import models


class Condition(models.Model):
    """A condition of the rules glossary (Blinded ... Unconscious, Exhaustion) or one of the
    glossary's other named states (`kind="status"`: Bloodied, Concentration, Surprised),
    sourced from db/conditions.json (`condition` and `status` lists).

    Only the rules text is data. What a condition *does* to a character's numbers (Speed 0,
    Disadvantage on attacks, the Exhaustion penalty) is code in
    `apps/characters/conditions.py`; `tests/test_conditions.py` fails if the two stop agreeing.
    """

    KIND_CONDITION = "condition"
    KIND_STATUS = "status"

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, default=KIND_CONDITION)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated_fields = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

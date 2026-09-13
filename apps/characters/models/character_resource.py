from django.db import models


class CharacterResource(models.Model):
    """A limited-use resource of a Character (Rage, Sorcery Points, Channel Divinity, Bardic
    Inspiration, Superiority Dice, ...).

    `name` is free text rather than an FK: there's no standalone resource catalog in `db/`, but
    it should match the literal column header the resource's max count came from in
    `rules.ClassLevel.columns` (e.g. "Rages", "Sorcery Points") - that's guidance for whoever
    wires up the builder, not something enforced by this model, since not every resource
    necessarily comes from a class table row (a feat or magic item could grant one too).

    `reset_on` is left blank-able rather than required: which rest type restores a given
    resource is stated in that resource's own rulebook description, not captured anywhere in
    `db/` in structured form, so the builder will need to set it explicitly per resource rather
    than deriving it automatically.
    """

    RESET_CHOICES = [
        ("short_rest", "Short Rest"),
        ("long_rest", "Long Rest"),
        ("other", "Other"),
    ]

    character = models.ForeignKey(
        "characters.Character", related_name="resources", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)
    max_uses = models.PositiveSmallIntegerField()
    current_uses = models.PositiveSmallIntegerField()
    reset_on = models.CharField(max_length=20, choices=RESET_CHOICES, blank=True)

    class Meta:
        ordering = ["character", "name"]
        constraints = [
            models.UniqueConstraint(fields=["character", "name"], name="unique_character_resource"),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.name} ({self.current_uses}/{self.max_uses})"

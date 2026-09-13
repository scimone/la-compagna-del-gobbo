from django.db import models


class CharacterLanguage(models.Model):
    """A language a Character knows (see `rules.Language`).

    Added to the model tree beyond architecture.md's original list: `rules.Language` didn't
    exist yet when that list was drafted, and species/background/feats all grant languages with
    nowhere to record them.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="languages", on_delete=models.CASCADE
    )
    language = models.ForeignKey("rules.Language", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["character", "language"]
        constraints = [
            models.UniqueConstraint(
                fields=["character", "language"], name="unique_character_language"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.language.name}"

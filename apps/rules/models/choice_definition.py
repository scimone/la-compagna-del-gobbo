from django.db import models


class ChoiceDefinition(models.Model):
    """A choice a player must make (e.g. pick 2 skills).

    Not populated from db/: choices are described only as prose (e.g. Background.ability_scores
    = "Choose from Intelligence, Wisdom, Charisma"), not as a structured, referenceable catalog.
    TODO: define fields once choices need to be resolved/validated by the builder app.
    """

    def __str__(self) -> str:
        return f"ChoiceDefinition #{self.pk}"

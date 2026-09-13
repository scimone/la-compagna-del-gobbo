from django.db import models


class Proficiency(models.Model):
    """A proficiency category (weapon/armor/save/etc.).

    Not populated from db/: there is no proficiencies catalog file - proficiencies only appear
    as free text on Class/Background (e.g. Class.proficiencies, Class.armor_proficiencies).
    TODO: define fields if proficiencies need to become a referenceable catalog.
    """

    def __str__(self) -> str:
        return f"Proficiency #{self.pk}"

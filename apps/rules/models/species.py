from django.db import models


class Species(models.Model):
    """A player species (e.g. Elf, Dwarf). TODO: define fields."""

    def __str__(self) -> str:
        return f"Species #{self.pk}"

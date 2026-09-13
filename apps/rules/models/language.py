from django.db import models


class Language(models.Model):
    """A language (e.g. Common, Elvish). TODO: define fields."""

    def __str__(self) -> str:
        return f"Language #{self.pk}"

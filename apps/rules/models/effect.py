from django.db import models


class Effect(models.Model):
    """A mechanical effect attached to a Feature.

    Not populated from db/: same reason as `Feature` - mechanical effects are embedded in free
    text, not exposed as normalized data. TODO: define fields once `Feature` is addressed.
    """

    def __str__(self) -> str:
        return f"Effect #{self.pk}"

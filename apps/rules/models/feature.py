from django.db import models


class Feature(models.Model):
    """A discrete class/subclass/species/feat feature grant.

    Not populated from db/: features exist in the source only as free text nested inside their
    parent (Class.features, Subclass features, Species.entries, Feat.entries) - there is no
    normalized, standalone feature catalog to model without inventing structure that isn't
    there. TODO: define fields once/if features need to be addressed independently of their
    parent entry.
    """

    def __str__(self) -> str:
        return f"Feature #{self.pk}"

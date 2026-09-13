from django.db import models


class Tool(models.Model):
    """A tool (e.g. Thieves' Tools, Herbalism Kit).

    Not populated from db/: there is no standalone tools catalog - tools, instruments and gaming
    sets are just `rules.Equipment` rows whose `category` is "Tool", "Artisan's Tools",
    "Instrument" or "Gaming Set". TODO: decide whether a dedicated Tool model/table adds
    anything beyond filtering Equipment by category, or drop this placeholder.
    """

    def __str__(self) -> str:
        return f"Tool #{self.pk}"

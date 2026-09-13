import re

from django.db import models

#: Matches a literal 5etools inline tag, e.g. `{@damage 1d6}`, `{@condition Blinded|XPHB}`,
#: `{@dc 8}`, `{@variantrule Resistance|XPHB}`. There is no import command yet (see README); this
#: is exposed here so a future one reuses the exact same pattern instead of redefining it.
TAG_PATTERN = re.compile(r"\{@(\w+)[^}]*\}")


class Effect(models.Model):
    """A mechanical effect attached to a Feature - specifically, one literal 5etools inline tag
    (e.g. `{@damage 1d6}`, `{@condition Blinded|XPHB}`, `{@dc 8}`, `{@variantrule
    Resistance|XPHB}`, `{@skill Insight|XPHB}`) found somewhere in a `Feature`'s `entries` text.

    These tags are already a machine-parseable token embedded verbatim in the source prose, not
    something inferred from it. Extraction is purely mechanical: `TAG_PATTERN` walked over every
    string found anywhere in a `Feature`'s `entries` tree (recursively - tags occur at every
    nesting depth, inside nested "entries"/"items"/"rows" alike), storing the tag name and the
    raw tag text unchanged. No tag is reinterpreted into a new semantic field (there is
    deliberately no "damage_amount" or "resistance_type" column) - `tag` is copied verbatim from
    the `{@TAG ...}` name, and `raw` is the untouched tag text, including its `|`-separated
    arguments exactly as written.

    This makes `Effect` a partial, mechanical index, not a semantic effects model: it tells you
    *that* a Feature's text references a damage roll, a DC, a condition, etc., and exactly what
    the source said, but not what that means in isolation from the surrounding sentence (which
    stays on `Feature.entries`, unmodified, alongside it).
    """

    feature = models.ForeignKey("rules.Feature", related_name="effects", on_delete=models.CASCADE)
    tag = models.CharField(max_length=50)
    raw = models.CharField(max_length=500)

    class Meta:
        ordering = ["feature", "tag"]

    def __str__(self) -> str:
        return self.raw

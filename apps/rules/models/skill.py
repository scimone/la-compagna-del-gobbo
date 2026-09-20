from django.db import models


class Skill(models.Model):
    """A skill (e.g. Athletics, Perception), sourced from db/skills.json."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated_fields = models.JSONField(default=list, blank=True)
    ability = models.ForeignKey("rules.Ability", related_name="skills", on_delete=models.CASCADE)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

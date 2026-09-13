from django.db import models


class CharacterProficiency(models.Model):
    """A proficiency (armor, weapon, tool, skill or saving throw) granted to a Character.

    Not FK'd exclusively to `rules.Proficiency`: that catalog only covers the flat
    Class/Background grants (85 rows - see its docstring), while proficiencies can also come
    from a species trait or a feat, which aren't in that catalog at all. So `category`/`name`
    are stored directly here (matching `rules.Proficiency`'s own shape), and
    `source_proficiency` is an optional provenance link back to the catalog row when the grant
    did come from one of those.

    `skill` links to the canonical `rules.Skill` row when `category == "skill"` (enabling clean
    joins/queries), left null otherwise. There is no equivalent canonical row to link for
    "saving_throw" (the six abilities aren't a `rules` catalog of their own), so for that
    category `name` just holds the ability name.

    `level` (proficient/expertise) is a single field shared across all categories rather than a
    skill-only concept: 2024 rules let Rogue's Expertise apply to a tool proficiency too, not
    just skills. It's simply unused (always "proficient") for armor/weapon/saving_throw.
    """

    CATEGORY_CHOICES = [
        ("armor", "Armor"),
        ("weapon", "Weapon"),
        ("tool", "Tool"),
        ("skill", "Skill"),
        ("saving_throw", "Saving Throw"),
    ]
    LEVEL_CHOICES = [
        ("proficient", "Proficient"),
        ("expertise", "Expertise"),
    ]

    character = models.ForeignKey(
        "characters.Character", related_name="proficiencies", on_delete=models.CASCADE
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    name = models.CharField(max_length=200)
    skill = models.ForeignKey(
        "rules.Skill", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    level = models.CharField(max_length=12, choices=LEVEL_CHOICES, default="proficient")
    source_proficiency = models.ForeignKey(
        "rules.Proficiency", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["character", "category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["character", "category", "name"], name="unique_character_proficiency"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.name} ({self.category})"

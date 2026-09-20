from django.db import models


class Bookmark(models.Model):
    """A `rules` catalog entry (a Background, Class, Feat, Species, Spell or Rule) starred by the
    user, shown at the top of its own World tab's list. Deliberately not a `bookmarked` flag on
    each of those models: every `rules` table is wiped and reloaded by `import_rules_data`, which
    would silently drop the user's choices - this table lives outside `rules`, and refers to a row
    only by `(kind, object_id)` (the slug pk, stable across re-imports), so it survives. There's no
    auth/ownership anywhere in the project yet, so a bookmark is global, not per user.

    No FK on purpose (`object_id` can't point at six different tables): a bookmark whose row later
    disappears from the catalog is simply never matched to a list item, and toggling one is
    validated against the catalog in `views.bookmark_toggle()`.
    """

    kind = models.CharField(max_length=20)
    object_id = models.SlugField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "object_id"], name="unique_bookmark"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.object_id}"

from django.conf import settings
from django.db import models


class Bookmark(models.Model):
    """A `rules` catalog entry (a Background, Class, Feat, Species, Spell or Rule) starred by a
    user, shown at the top of its own World tab's list. Deliberately not a `bookmarked` flag on
    each of those models: every `rules` table is wiped and reloaded by `import_rules_data`, which
    would silently drop the user's choices - this table lives outside `rules`, and refers to a row
    only by `(kind, object_id)` (the slug pk, stable across re-imports), so it survives. Each
    bookmark belongs to one `auth.User` (see `accounts.py` for the password-less sign-in).

    No FK to the catalog on purpose (`object_id` can't point at six different tables): a
    bookmark whose row later disappears from the catalog is simply never matched to a list item,
    and toggling one is validated against the catalog in `views.bookmark_toggle()`.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks"
    )
    kind = models.CharField(max_length=20)
    object_id = models.SlugField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "object_id"], name="unique_user_bookmark"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.object_id}"


class LogEntry(models.Model):
    """One entry of the party's shared Logbook: what happened at a session. Lives in `frontend`
    next to `Bookmark` - it is user-written content, not `rules` data, so `import_rules_data`
    never touches it. Every field but the date is optional free text, so an entry can be a
    single line or a full recap. Anyone signed in may add one; only its author (or an
    administrator, see `logbook.can_edit`) changes or deletes it. `author` is kept as NULL if
    the account is ever removed - the story stays.
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="log_entries",
    )
    date = models.DateField()
    title = models.CharField(max_length=150, blank=True)
    location = models.CharField(max_length=150, blank=True)
    characters_met = models.TextField(blank=True)
    fights = models.TextField(blank=True)
    objectives = models.TextField(blank=True)
    insights = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.date} {self.title or self.location}".strip()

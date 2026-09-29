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
    location = models.TextField(blank=True)  # the visited locations, one per line like the rest
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


class TranslationJob(models.Model):
    """One piece of player-written text waiting for, or holding, its machine translation
    between the site's two languages (Logbook entries, character backstories).

    The web process only ever *writes* jobs (`translations.enqueue`); the separate
    `translate_worker` process - the only one given the LLM credentials - fills in `result`.
    `source` snapshots the text as it was when queued, so a translation is shown only while it
    still matches the current text (`translations.translated`): editing the original never
    displays a stale translation. Nothing here is trusted - `result` comes from a language
    model that read user-written text - so it is only ever rendered escaped, as plain text.
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STATUS_CHOICES = [(s, s) for s in (PENDING, RUNNING, DONE, FAILED)]

    kind = models.CharField(max_length=20)
    object_id = models.PositiveIntegerField()
    source_lang = models.CharField(max_length=8)
    target_lang = models.CharField(max_length=8)
    source = models.JSONField()  # {field: text}
    result = models.JSONField(null=True, blank=True)  # {field: translated text}
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["kind", "object_id"]),
            models.Index(fields=["status", "id"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.object_id} {self.source_lang}->{self.target_lang} {self.status}"


class Interaction(models.Model):
    """One thing a visitor did in the app: a page they opened (`kind="view"`) or a change they
    posted (`kind="action"`), written by `middleware.InteractionMiddleware` for every request that
    is not a static file. It records *where* and *what*, never request bodies: no typed text
    (except the search box's, `query`), no passwords, no addresses or browser strings - so the
    table can answer "who used what, when" without becoming a copy of the users' data.

    `user` is nulled if the account is deleted; `username` keeps the name as it was, and `session`
    (a short hash, never the session key itself) groups the visits of someone not signed in.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="interactions",
    )
    username = models.CharField(max_length=150, blank=True)
    session = models.CharField(max_length=16, blank=True)
    kind = models.CharField(max_length=10)  # "view" (GET) or "action" (anything else)
    route = models.CharField(
        max_length=100, blank=True
    )  # the URL's name, e.g. "world-spell-detail"
    path = models.CharField(max_length=300)
    method = models.CharField(max_length=8)
    status = models.PositiveSmallIntegerField()
    object_id = models.CharField(max_length=100, blank=True)  # the page's pk/slug, when it has one
    action = models.CharField(max_length=50, blank=True)  # a posted `action` (e.g. "hp_delta")
    query = models.CharField(max_length=200, blank=True)  # the search box's text
    language = models.CharField(max_length=8, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["route", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.username or 'anonymous'} {self.method} {self.path} {self.status}"

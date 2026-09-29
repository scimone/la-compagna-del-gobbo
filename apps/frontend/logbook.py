"""The Logbook's rules: who may change an entry, and the list a page shows."""

from apps.characters.services import access
from apps.frontend.models import LogEntry


def list_entries():
    """Newest session first (see `LogEntry.Meta.ordering`)."""
    return LogEntry.objects.select_related("author")


def can_edit(user, entry: LogEntry) -> bool:
    """The author, or an administrator. Anyone else - and a signed-out visitor - only reads."""
    if access.is_admin(user):
        return True
    return bool(
        getattr(user, "is_authenticated", False)
        and entry.author_id is not None
        and entry.author_id == user.id
    )

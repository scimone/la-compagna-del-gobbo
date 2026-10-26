"""The Logbook's rules: who may change an entry, and the list a page shows."""

from secrets import token_hex

from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.templatetags.static import static
from django.urls import reverse

from apps.campaigns.services import membership
from apps.characters.services.portrait import _encode
from apps.frontend import translations
from apps.frontend.handbook_search import fold, query_pattern
from apps.frontend.models import LogEntry, LogEntryImage


def _order(entry: LogEntry) -> tuple:
    personal = entry.kind == LogEntry.PERSONAL
    written = entry.created_at.timestamp()
    return (entry.date.toordinal(), not personal, written, entry.pk)


def list_entries(campaign) -> list[LogEntry]:
    """Oldest first, so the newest is at the bottom like in a chat. Within a day the personal
    messages come first and the objective entries follow under them, each in the order they were
    written. Only `campaign`'s journal."""
    entries = (
        LogEntry.objects.filter(campaign=campaign)
        .select_related("author", "character")
        .prefetch_related("images")
    )
    return sorted(entries, key=_order)


DM_AVATAR = "images/dm-256.png"
DM_FULL = "images/dm-1024.png"


def avatar_url(entry: LogEntry) -> str:
    """The round picture of a personal entry's character, or "" (a silhouette is shown then).
    The DM's is a fixed static picture (`static/images/dm.webp`), shown zoomed in by the page."""
    if entry.as_dm:
        return static(DM_AVATAR) if finders.find(DM_AVATAR) else ""
    character = entry.character
    if character is None or not character.portrait:
        return ""
    version = (
        f"{character.portrait.name}-{character.portrait_cx:.4f}-"
        f"{character.portrait_cy:.4f}-{character.portrait_zoom:.3f}"
    )
    return f"{reverse('character-avatar', args=[character.pk])}?v={version}"


def full_url(entry: LogEntry) -> str:
    """The whole, unzoomed picture behind `avatar_url`, or "" when there is none."""
    if entry.as_dm:
        return static(DM_FULL) if finders.find(DM_FULL) else avatar_url(entry)
    character = entry.character
    if character is None or not character.portrait:
        return ""
    return f"{reverse('character-portrait', args=[character.pk])}?v={character.portrait.name}"


def can_edit(user, entry: LogEntry) -> bool:
    """The author (while still in the campaign), the campaign's DM, or an administrator. Anyone
    else only reads."""
    if not getattr(user, "is_authenticated", False):
        return False
    if membership.can_manage(user, entry.campaign):
        return True
    return (
        entry.author_id is not None
        and entry.author_id == user.id
        and membership.is_member(user, entry.campaign)
    )


TEXT_FIELDS = ("title", "text")


def texts(entry: LogEntry) -> dict[str, str]:
    """What of an entry is translated: its title and text (not the date)."""
    return {name: getattr(entry, name) for name in TEXT_FIELDS}


def queue_translation(entry: LogEntry) -> None:
    translations.enqueue("logentry", entry.pk, texts(entry))


def search(entries: list[LogEntry], q: str) -> list[LogEntry]:
    """The entries with `q` in any text - as written or in either language's translation,
    ignoring case and accents."""
    pattern = query_pattern(q)
    haystacks = translations.search_text("logentry", {e.pk: texts(e) for e in entries})
    return [e for e in entries if pattern.search(fold(haystacks[e.pk]))]


def display(entries: list[LogEntry]) -> dict[int, dict[str, tuple[str, bool]]]:
    """`{entry pk: {field: (text to show, is it machine-translated)}}` in the active language."""
    return translations.translated_texts("logentry", {e.pk: texts(e) for e in entries})


#: Pictures one entry can hold.
MAX_IMAGES = 12


def encode_images(uploads, already=0) -> list[bytes]:
    """The uploads as shrunk WebPs, all or nothing. Raises `ValueError` for the first unusable one
    or when the entry would hold more than `MAX_IMAGES`."""
    from django.utils.translation import gettext as _

    if already + len(uploads) > MAX_IMAGES:
        raise ValueError(_("An entry can hold %(n)d pictures at most.") % {"n": MAX_IMAGES})
    return [_encode(upload) for upload in uploads]


def add_images(entry: LogEntry, encoded: list[bytes]) -> None:
    for data in encoded:
        image = LogEntryImage(entry=entry)
        image.image.save(f"{entry.pk}-{token_hex(4)}.webp", ContentFile(data), save=False)
        image.save()


def remove_images(entry: LogEntry, ids) -> None:
    """Delete the entry's pictures with these ids (and their files); other ids are ignored."""
    for image in entry.images.filter(pk__in=ids):
        delete_image(image)


def delete_image(image: LogEntryImage) -> None:
    name, storage = image.image.name, image.image.storage
    image.delete()
    storage.delete(name)


def delete_entry(entry: LogEntry) -> None:
    set_banner(entry, None, remove=True)
    for image in list(entry.images.all()):
        delete_image(image)
    entry.delete()


def banner_url(entry: LogEntry) -> str:
    """Where the entry's banner is served from, or "" (the name in the query busts the cache)."""
    if not entry.banner:
        return ""
    return f"{reverse('logbook-banner', args=[entry.pk])}?v={entry.banner.name}"


def encode_banner(upload) -> bytes | None:
    """The banner upload as a shrunk WebP (`ValueError` if unusable), None when none was sent."""
    return _encode(upload) if upload else None


def set_banner(entry: LogEntry, data: bytes | None, remove: bool = False) -> None:
    """Replace the banner with the encoded `data`, or drop it (`remove`); neither leaves it."""
    if data is None and not remove:
        return
    old = entry.banner.name
    storage = entry.banner.storage
    if data is None:
        entry.banner = ""
    else:
        entry.banner.save(f"{entry.pk}-{token_hex(4)}.webp", ContentFile(data), save=False)
    entry.banner_x = entry.banner_y = 0.5
    entry.banner_zoom = 1.0
    entry.save(update_fields=["banner", "banner_x", "banner_y", "banner_zoom"])
    if old:
        storage.delete(old)


BANNER_MAX_ZOOM = 3.0


def banner_style(entry: LogEntry) -> str:
    """The CSS that frames the banner in its wide box: the focus point is where the picture is
    anchored (`object-position`) and where a zoom grows from (`transform-origin`). The form's
    editor sets the very same properties, so what it shows is what the logbook shows."""
    x, y = f"{entry.banner_x * 100:.1f}%", f"{entry.banner_y * 100:.1f}%"
    style = f"object-position: {x} {y};"
    if entry.banner_zoom > 1:
        style += f" transform-origin: {x} {y}; transform: scale({entry.banner_zoom:.3f});"
    return style


def set_banner_frame(entry: LogEntry, x, y, zoom) -> None:
    """Store the frame (non-numbers are ignored, numbers clamped into range)."""
    try:
        x, y, zoom = float(x), float(y), float(zoom)
    except (TypeError, ValueError):
        return
    if not all(v == v and abs(v) != float("inf") for v in (x, y, zoom)):
        return
    entry.banner_x = min(max(x, 0.0), 1.0)
    entry.banner_y = min(max(y, 0.0), 1.0)
    entry.banner_zoom = min(max(zoom, 1.0), BANNER_MAX_ZOOM)
    entry.save(update_fields=["banner_x", "banner_y", "banner_zoom"])

"""What the admin panel shows (`admin_views.py` is the HTTP side): the app's `Interaction` log,
optionally narrowed to one visitor, turned into sentences an administrator can read - "Opened the
spell Fireball", "Changed hit points of Gandalf" - with a link to the page concerned.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.characters.models import Character
from apps.frontend import accounts
from apps.frontend.models import Interaction, LogEntry
from apps.rules import models as rules

#: The filter value that means "visits by nobody signed in".
ANONYMOUS = "__anonymous__"

#: Which model a route's `object_id` names, and the url name of that object's own page.
_SUBJECTS = {
    "character": (Character, "character-detail"),
    "background": (rules.Background, "world-background-detail"),
    "class": (rules.Class, "world-class-detail"),
    "species": (rules.Species, "world-species-detail"),
    "feat": (rules.Feat, "world-feat-detail"),
    "feature": (rules.Feature, "world-feature-detail"),
    "option": (rules.OptionalFeature, "world-option-detail"),
    "spell": (rules.Spell, "world-spell-detail"),
    "item": (rules.Equipment, "world-item-detail"),
    "rule": (rules.Rule, "world-rule-detail"),
    "section": (rules.HandbookSection, "handbook-section-detail"),
    "logentry": (LogEntry, None),
}


def _route_table():
    """route -> (section, subject kind or None, sentence). Built per call so the sentences are
    translated into the viewer's language. `%(name)s` is the subject's name."""
    return {
        "index": ("app", None, _("Opened the home page")),
        "account": ("app", None, _("Opened the account page")),
        "welcome": ("app", None, _("Gave a name to a new account")),
        "account-logout": ("app", None, _("Signed out")),
        "bookmark-toggle": ("app", None, _("Added or removed a bookmark")),
        "characters-overview": ("characters", None, _("Browsed the character list")),
        "character-new": ("characters", None, _("Started creating a character")),
        "character-describe": ("characters", None, _("Read about a creation choice")),
        "character-detail": ("characters", "character", _("Opened the sheet of %(name)s")),
        "character-levelup": ("characters", "character", _("Levelled up %(name)s")),
        "character-levelup-done": ("characters", "character", _("Finished levelling up %(name)s")),
        "character-export-pdf": ("characters", "character", _("Exported %(name)s to PDF")),
        "character-reopen": ("characters", "character", _("Reopened creation of %(name)s")),
        "character-delete": ("characters", "character", _("Deleted the character %(name)s")),
        "character-assign": ("characters", "character", _("Reassigned %(name)s to a user")),
        "character-act": ("characters", "character", _("Played %(name)s")),
        "character-items": ("characters", "character", _("Browsed the items of %(name)s")),
        "character-spells": ("characters", "character", _("Browsed the spells of %(name)s")),
        "character-features": ("characters", "character", _("Browsed the features of %(name)s")),
        "character-stack-item": ("characters", "character", _("Opened an item of %(name)s")),
        "character-custom-item": ("characters", "character", _("Opened a custom item of %(name)s")),
        "character-catalog-item": (
            "characters",
            "character",
            _("Opened a catalog item for %(name)s"),
        ),
        "character-portrait": ("characters", "character", _("Changed the portrait of %(name)s")),
        "character-avatar": ("characters", "character", _("Changed the avatar of %(name)s")),
        "character-gallery": ("characters", "character", _("Opened the gallery of %(name)s")),
        "character-gallery-picture": ("characters", "character", _("Opened a picture of %(name)s")),
        "character-finish": ("characters", "character", _("Finished creating %(name)s")),
        "character-discard": ("characters", "character", _("Discarded the draft %(name)s")),
        "character-wizard": ("characters", "character", _("Worked on creating %(name)s")),
        "handbook-overview": ("handbook", None, _("Browsed the handbook chapters")),
        "handbook-rules-glossary": ("handbook", None, _("Browsed the rules glossary")),
        "handbook-section-detail": ("handbook", "section", _("Read the handbook section %(name)s")),
        "logbook-list": ("logbook", None, _("Opened the logbook")),
        "logbook-preview": ("logbook", None, _("Previewed a logbook entry")),
        "logbook-new": ("logbook", None, _("Wrote a new logbook entry")),
        "logbook-edit": ("logbook", "logentry", _("Edited the logbook entry %(name)s")),
        "logbook-delete": ("logbook", "logentry", _("Deleted the logbook entry %(name)s")),
        "world-overview": ("world", None, _("Opened the World")),
        "world-backgrounds": ("world", None, _("Browsed the backgrounds")),
        "world-background-detail": ("world", "background", _("Read the background %(name)s")),
        "world-classes": ("world", None, _("Browsed the classes")),
        "world-class-detail": ("world", "class", _("Read the class %(name)s")),
        "world-feats": ("world", None, _("Browsed the features")),
        "world-feat-detail": ("world", "feat", _("Read the feat %(name)s")),
        "world-feature-detail": ("world", "feature", _("Read the class feature %(name)s")),
        "world-option-detail": ("world", "option", _("Read the option %(name)s")),
        "world-species": ("world", None, _("Browsed the species")),
        "world-species-detail": ("world", "species", _("Read the species %(name)s")),
        "world-spells": ("world", None, _("Browsed the spells")),
        "world-spell-detail": ("world", "spell", _("Read the spell %(name)s")),
        "world-items": ("world", None, _("Browsed the equipment")),
        "world-item-detail": ("world", "item", _("Read the item %(name)s")),
        "world-rule-detail": ("world", "rule", _("Read the rule %(name)s")),
        "admin-panel": ("admin", None, _("Opened the admin panel")),
        "admin-activity": ("admin", None, _("Opened the activity log")),
    }


def _section_labels():
    return {
        "app": _("App"),
        "characters": _("Characters"),
        "handbook": _("Handbook"),
        "logbook": _("Logbook"),
        "world": _("World"),
        "admin": _("Admin"),
    }


def _action_labels():
    """What a posted `action` of a character sheet does, as a sentence ending the "Played X"."""
    return {
        "name": _("Renamed the character"),
        "xp": _("Changed experience points"),
        "hp_delta": _("Changed hit points"),
        "hp_set": _("Set hit points"),
        "temp_hp": _("Set temporary hit points"),
        "death_toggle": _("Marked a death saving throw"),
        "inspiration": _("Toggled Inspiration"),
        "hit_dice": _("Spent or regained Hit Dice"),
        "slots": _("Changed spell slots"),
        "coin": _("Changed coins"),
        "text": _("Edited a text field (notes, backstory...)"),
        "equip": _("Equipped or unequipped an item"),
        "item_add": _("Added an item"),
        "item_buy": _("Bought an item"),
        "custom_add": _("Added a custom item"),
        "item_qty": _("Changed an item's quantity"),
        "item_remove": _("Removed an item"),
        "item_sell": _("Sold an item"),
        "cast": _("Cast a spell"),
        "short_rest": _("Took a short rest"),
        "long_rest": _("Took a long rest"),
        "feature_use": _("Used a feature"),
        "wild_shape_use": _("Used Wild Shape"),
        "wild_shape_end": _("Ended Wild Shape"),
        "rest_decline": _("Turned down a rest's offer"),
        "spell_add": _("Added a spell"),
        "spell_prepare": _("Prepared or unprepared a spell"),
        "spell_remove": _("Removed a spell"),
        "feature_add": _("Added a feature"),
        "feature_remove": _("Removed a feature"),
    }


def visitors() -> list[dict]:
    """Everyone who has an interaction on record, most active first, for the filter's menu:
    `{"username", "name", "count"}` - `username` is the filter's value, `name` what to show (the
    name the person gave, else the username); an empty username is the signed-out visitors."""
    rows = (
        Interaction.objects.values("username")
        .annotate(count=Count("id"))
        .order_by("-count", "username")
    )
    users = {u.username: u for u in get_user_model().objects.all()}
    return [
        {
            "username": r["username"],
            "name": accounts.display_name(users[r["username"]])
            if r["username"] in users
            else r["username"],
            "count": r["count"],
        }
        for r in rows
    ]


def interactions(username: str = ""):
    """The log, newest first. `username` narrows it to one visitor (`ANONYMOUS` for signed-out
    ones); empty means everyone."""
    qs = Interaction.objects.select_related("user").order_by("-created_at", "-id")
    if username == ANONYMOUS:
        qs = qs.filter(username="")
    elif username:
        qs = qs.filter(username=username)
    return qs


def _names(rows) -> dict:
    """`{(subject kind, object_id): name}` for every object the rows refer to - one query per
    kind, not per row. An object that no longer exists is simply missing."""
    table = _route_table()
    wanted: dict[str, set] = {}
    for row in rows:
        subject = table.get(row.route, (None, None, None))[1]
        if subject and row.object_id:
            wanted.setdefault(subject, set()).add(row.object_id)
    names = {}
    for subject, ids in wanted.items():
        model = _SUBJECTS[subject][0]
        pk_is_int = model._meta.pk.get_internal_type() in ("AutoField", "BigAutoField")
        keys = [i for i in ids if i.isdigit()] if pk_is_int else list(ids)
        for obj in model.objects.filter(pk__in=keys):
            label = getattr(obj, "name", "") or getattr(obj, "title", "") or str(obj)
            names[(subject, str(obj.pk))] = label
    return names


def describe(rows) -> list[dict]:
    """Each row as `{"row", "section", "text", "detail", "url"}`: a sentence saying what the
    visitor did, a smaller line with the extra (search text, the thing's status), and the page
    to look at - the page itself for something opened, the affected page for something changed
    (None once the thing is gone, or when it has no page of its own)."""
    rows = list(rows)
    table, sections, actions = _route_table(), _section_labels(), _action_labels()
    names = _names(rows)
    out = []
    for row in rows:
        section, subject, sentence = table.get(row.route, (None, None, None))
        name = names.get((subject, row.object_id)) if subject else None
        if sentence is None:
            section, text = "app", _("Opened %(path)s") % {"path": row.path}
        else:
            shown = name if name is not None else f"#{row.object_id}"
            text = sentence % {"name": shown} if subject else sentence
        detail = []
        if row.route == "character-act" and row.action:
            detail.append(actions.get(row.action, row.action))
        elif row.action:
            detail.append(row.action)
        if row.query:
            detail.append(_("searched for “%(text)s”") % {"text": row.query})
        if subject and row.object_id and name is None:
            detail.append(_("no longer exists"))
        if row.status >= 400:
            detail.append(_("failed (%(status)s)") % {"status": row.status})
        out.append(
            {
                "row": row,
                "who": accounts.display_name(row.user) if row.user else row.username,
                "section": section,
                "section_label": sections.get(section, ""),
                "text": text,
                "detail": " · ".join(detail),
                "url": _link(row, subject, name),
            }
        )
    return out


def _link(row, subject, name) -> str | None:
    """Where the row's page can be seen again. A GET that worked links to its own path (with
    the search text, so the list reads as it did); a change links to the thing it changed."""
    if row.kind == "view":
        if row.status != 200 or (subject and name is None):
            return None
        return row.path + (f"?q={row.query}" if row.query else "")
    page = _SUBJECTS[subject][1] if subject else None
    if page and name is not None and row.object_id:
        return reverse(page, args=[row.object_id])
    return None


def by_day(entries: list[dict]) -> list[dict]:
    """The described rows (already newest first) cut into days, each headed "Today",
    "Yesterday" or its date - a long log reads as a diary instead of a wall of timestamps."""
    today = timezone.localdate()
    days: list[dict] = []
    for entry in entries:
        day = timezone.localtime(entry["row"].created_at).date()
        if not days or days[-1]["date"] != day:
            if day == today:
                label = _("Today")
            elif day == today - timedelta(days=1):
                label = _("Yesterday")
            else:
                label = ""
            days.append({"date": day, "label": label, "entries": []})
        days[-1]["entries"].append(entry)
    return days

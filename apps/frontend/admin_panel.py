"""What the admin panel shows (`admin_views.py` is the HTTP side): the app's `Interaction` log,
optionally narrowed to one visitor."""

from django.db.models import Count

from apps.frontend.models import Interaction

#: The filter value that means "visits by nobody signed in".
ANONYMOUS = "__anonymous__"


def visitors() -> list[dict]:
    """Everyone who has an interaction on record, most active first, for the filter's menu:
    `{"username", "count"}` - an empty username is the signed-out visitors."""
    rows = (
        Interaction.objects.values("username")
        .annotate(count=Count("id"))
        .order_by("-count", "username")
    )
    return [{"username": r["username"], "count": r["count"]} for r in rows]


def interactions(username: str = ""):
    """The log, newest first. `username` narrows it to one visitor (`ANONYMOUS` for signed-out
    ones); empty means everyone."""
    qs = Interaction.objects.all()
    if username == ANONYMOUS:
        qs = qs.filter(username="")
    elif username:
        qs = qs.filter(username=username)
    return qs

"""The admin panel: pages only administrators (`access.is_admin`) may open. Anyone else gets a
404, so the panel's existence isn't advertised."""

from zoneinfo import ZoneInfo

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _

from apps.characters.services import access
from apps.frontend import admin_panel

PAGE_SIZE = 50
#: Times are stored in UTC; the panel shows the group's own clock.
TIME_ZONE = ZoneInfo("Europe/Berlin")


def _require_admin(request) -> None:
    if not access.is_admin(request.user):
        raise Http404


def panel_home(request):
    _require_admin(request)
    return render(
        request,
        "frontend/admin/home.html",
        {"page_title": _("Admin panel"), "back_url": reverse("account")},
    )


def panel_activity(request):
    """Every page opened and change posted in the app, newest first, filterable by user."""
    _require_admin(request)
    with timezone.override(TIME_ZONE):
        selected = request.GET.get("user", "")
        changes_only = request.GET.get("changes") == "1"
        page = Paginator(admin_panel.interactions(selected, changes_only), PAGE_SIZE).get_page(
            request.GET.get("page")
        )
        days = admin_panel.by_day(admin_panel.describe(page))
        response = render(
            request,
            "frontend/admin/activity.html",
            {
                "page_title": _("Activity"),
                "back_url": reverse("admin-panel"),
                "page": page,
                "days": days,
                "selected": selected,
                "changes_only": changes_only,
                "anonymous": admin_panel.ANONYMOUS,
                "visitors": admin_panel.visitors(),
            },
        )
    add_never_cache_headers(response)
    return response

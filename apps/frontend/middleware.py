import hashlib
import logging
from datetime import timedelta

from django.utils import timezone

# Path prefix -> session key. The bottom nav's destinations (Characters/Logbook/World)
# each have their own sub-navigation (World's category tabs and detail pages, Handbook's section
# detail pages) - without this, switching to another bottom-nav tab and back always resets to
# that section's landing page, discarding whatever the user had drilled into.
_TRACKED_SECTIONS = {
    "/characters/": "last_characters_url",
    "/handbook/": "last_world_url",  # the Rules tab of the Handbook
    "/world/": "last_world_url",
}


class TrackLastSectionUrlMiddleware:
    """Remembers the last successfully-rendered page within each bottom-nav section, so the
    section's own nav link (see `base.html`'s `.bottom-nav`) can return there instead of always
    resetting to that section's landing page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Only plain page loads, not redirects.
        if request.method == "GET" and response.status_code == 200:
            for prefix, session_key in _TRACKED_SECTIONS.items():
                if request.path.startswith(prefix):
                    # Writing an unchanged value still saves the session (a DB write per page).
                    if request.session.get(session_key) != request.path:
                        request.session[session_key] = request.path
                    break
        return response


log = logging.getLogger(__name__)

#: Requests that are not something a person did: the app's own files and pictures.
_UNTRACKED_PREFIXES = ("/static/", "/media/")
_UNTRACKED_PATHS = ("/manifest.json", "/serviceworker.js", "/favicon.ico")
_UNTRACKED_ROUTES = ("character-portrait",)
#: A search box fires a request per keystroke; requests for the same page within this many
#: seconds are one search whose text is the last one.
_SEARCH_MERGE = timedelta(seconds=5)


class InteractionMiddleware:
    """Writes an `Interaction` row for every page opened and every change posted - see that
    model for what is (and is not) kept. It never gets in the way: a failure to record is logged
    and the response goes out untouched."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        before = getattr(request, "user", None)
        response = self.get_response(request)
        try:
            self._record(request, response, before)
        except Exception:  # noqa: BLE001 - tracking must never break a page
            log.exception("could not record an interaction")
        return response

    def _record(self, request, response, before) -> None:
        from apps.frontend.models import Interaction

        path = request.path
        if request.method in ("HEAD", "OPTIONS") or path.startswith(_UNTRACKED_PREFIXES):
            return
        if path in _UNTRACKED_PATHS:
            return
        match = request.resolver_match
        route = match.url_name if match and match.url_name else ""
        if route in _UNTRACKED_ROUTES and request.method == "GET":
            return
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            user = before if getattr(before, "is_authenticated", False) else None  # logging out
        key = request.session.session_key if hasattr(request, "session") else None
        session = hashlib.sha256(key.encode()).hexdigest()[:16] if key else ""
        kwargs = match.kwargs if match else {}
        object_id = str(next(iter(kwargs.values()), ""))[:100] if kwargs else ""
        query = request.GET.get("q", "").strip()[:200]
        fields = {
            "user": user,
            "username": user.get_username() if user else "",
            "session": session,
            "kind": "view" if request.method == "GET" else "action",
            "route": route[:100],
            "path": path[:300],
            "method": request.method,
            "status": response.status_code,
            "object_id": object_id,
            "action": request.POST.get("action", "")[:50] if request.method == "POST" else "",
            "query": query,
            "language": (getattr(request, "LANGUAGE_CODE", "") or "")[:8],
        }
        if query and request.method == "GET":
            recent = (
                Interaction.objects.filter(
                    user=user,
                    session=session,
                    path=fields["path"],
                    kind="view",
                    created_at__gte=timezone.now() - _SEARCH_MERGE,
                )
                .exclude(query="")
                .first()
            )
            if recent:
                recent.query, recent.status = query, fields["status"]
                recent.save(update_fields=["query", "status"])
                return
        Interaction.objects.create(**fields)

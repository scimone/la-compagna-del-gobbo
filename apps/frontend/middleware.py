# Path prefix -> session key. The bottom nav's three destinations (Characters/Handbook/World)
# each have their own sub-navigation (World's category tabs and detail pages, Handbook's section
# detail pages) - without this, switching to another bottom-nav tab and back always resets to
# that section's landing page, discarding whatever the user had drilled into.
_TRACKED_SECTIONS = {
    "/characters/": "last_characters_url",
    "/handbook/": "last_handbook_url",
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
        # Only plain page loads, not redirects (e.g. `/world/` itself bounces to `/world/
        # backgrounds/` - storing the bounce-page's own URL would just recreate the loop).
        if request.method == "GET" and response.status_code == 200:
            for prefix, session_key in _TRACKED_SECTIONS.items():
                if request.path.startswith(prefix):
                    request.session[session_key] = request.path
                    break
        return response

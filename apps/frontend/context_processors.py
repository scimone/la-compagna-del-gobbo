from django.urls import reverse

# Mirrors `middleware.TrackLastSectionUrlMiddleware`'s session keys, plus each section's default
# landing page to fall back on the first visit (before the middleware has stored anything).
_SECTION_DEFAULTS = {
    "last_characters_url": "characters-overview",
    "last_handbook_url": "handbook-overview",
    "last_world_url": "world-overview",
}


def last_section_urls(request):
    """Exposes each bottom-nav section's last-visited URL to every template, so `base.html`'s
    `.bottom-nav` links can resume where the user left off (see `middleware.py`) instead of
    hardcoding each section's landing page.
    """
    session = getattr(request, "session", None)
    return {
        context_key: (session.get(context_key) if session else None) or reverse(url_name)
        for context_key, url_name in _SECTION_DEFAULTS.items()
    }

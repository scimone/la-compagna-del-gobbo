import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path: str) -> str:
    """`{% static %}` plus `?v=<file mtime>`. The static files are served under fixed names, so
    without a changing URL a browser keeps running an old script against freshly deployed markup
    (a new bottom-nav item the cached `navigation.js` doesn't know about does nothing on tap)."""
    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    return f"{url}?v={int(os.path.getmtime(found))}"


@register.filter
def display_name(user) -> str:
    from apps.frontend import accounts

    return accounts.display_name(user)

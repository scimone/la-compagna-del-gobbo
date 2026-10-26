"""Links in the assistant's answers. The model is told which paths exist, but it is free text:
only links to this app's own handbook / character / logbook pages that really resolve are kept,
anything else (an invented path, a web address, `javascript:`) is reduced to its text."""

import re

from django.urls import Resolver404, resolve

_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
ALLOWED_PREFIXES = ("/characters/", "/world/", "/handbook/", "/logbook/")


def _ok(target: str) -> bool:
    path = re.split(r"[?#]", target, maxsplit=1)[0]
    if not path.startswith(ALLOWED_PREFIXES) or "//" in path:
        return False
    try:
        resolve(path)
    except Resolver404:
        return False
    return True


def clean(text: str) -> str:
    return _LINK.sub(lambda m: m.group(0) if _ok(m.group(2)) else m.group(1), text)

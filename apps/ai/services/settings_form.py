"""Validating and saving the admin panel's AI settings form."""

from urllib.parse import urlparse

from django.utils.translation import gettext as _

from apps.ai.models import AISettings
from apps.ai.services import crypto


def save(post) -> list[str]:
    """Apply a submitted form to the settings row; returns the (translated) errors, and saves
    nothing when there are any. A blank key field keeps the stored key; `clear_key` removes it."""
    errors = []
    base_url = post.get("base_url", "").strip().rstrip("/")
    if base_url and urlparse(base_url).scheme not in ("http", "https"):
        errors.append(_("The base URL must start with http:// or https://."))
    numbers = {}
    for name in ("max_context_chars", "daily_message_cap", "log_retention_days"):
        try:
            numbers[name] = max(0, int(post.get(name, "")))
        except ValueError:
            errors.append(_("%(field)s must be a number.") % {"field": name})
    if numbers.get("max_context_chars", 1) < 2000:
        errors.append(_("The context size must be at least 2000 characters."))
    if errors:
        return errors
    config = AISettings.load()
    config.enabled = post.get("enabled") == "on"
    config.base_url = base_url
    config.model = post.get("model", "").strip()[:200]
    config.system_prompt_extra = post.get("system_prompt_extra", "").strip()[:4000]
    for name, value in numbers.items():
        setattr(config, name, value)
    new_key = post.get("api_key", "").strip()
    if post.get("clear_key") == "on":
        config.api_key_encrypted = ""
    elif new_key:
        config.api_key_encrypted = crypto.encrypt(new_key)
    config.save()
    return []

"""Validating and saving a campaign's AI settings form."""

from urllib.parse import urlparse

from django.utils.translation import gettext as _

from apps.ai.services import crypto, urlcheck


def save(config, post, *, by_admin: bool) -> list[str]:
    """Apply a submitted form to `config`; returns the (translated) errors, and saves nothing
    when there are any. A blank key field keeps the stored key; `clear_key` removes it.

    A DM (not `by_admin`) may only use a public URL, and must type the key again when changing
    the URL - otherwise the stored key would be sent to an address of their choosing."""
    errors = []
    base_url = post.get("base_url", "").strip().rstrip("/")
    new_key = post.get("api_key", "").strip()
    changed = base_url != config.base_url
    if base_url and urlparse(base_url).scheme not in ("http", "https"):
        errors.append(_("The base URL must start with http:// or https://."))
    elif base_url and not by_admin and changed and not urlcheck.is_public(base_url):
        errors.append(_("That address is not reachable from the internet."))
    if (
        changed
        and not by_admin
        and config.has_key
        and not new_key
        and post.get("clear_key") != "on"
    ):
        errors.append(_("Enter the API key again when you change the URL."))
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
    config.enabled = post.get("enabled") == "on"
    config.use_tools = post.get("use_tools") == "on"
    if by_admin:
        config.allow_private_url = True
    elif changed:
        config.allow_private_url = False
    config.base_url = base_url
    config.model = post.get("model", "").strip()[:200]
    config.system_prompt_extra = post.get("system_prompt_extra", "").strip()[:4000]
    for name, value in numbers.items():
        setattr(config, name, value)
    if post.get("clear_key") == "on":
        config.api_key_encrypted = ""
    elif new_key:
        config.api_key_encrypted = crypto.encrypt(new_key)
    config.save()
    return []

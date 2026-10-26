"""The one place that calls the model with the administrator's key. Every call - chat or the
settings page's connection test - is written to `AIRequestLog`, with the exact messages and the
reply (never the key)."""

import time
from urllib.parse import urlparse

from django.utils.translation import gettext as _

from apps.ai.models import AIRequestLog, AISettings
from apps.ai.services import crypto
from apps.frontend import llm

TIMEOUT_SECONDS = 120


class AIUnavailable(Exception):
    """The model could not be asked or answered. The message is safe to show to the user."""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def ask(
    messages: list[dict],
    *,
    user=None,
    campaign=None,
    thread=None,
    purpose: str = AIRequestLog.Purpose.CHAT,
) -> str:
    config = AISettings.load()
    if purpose != AIRequestLog.Purpose.TEST and not config.enabled:
        raise AIUnavailable(_("The AI assistant is switched off."))
    key = crypto.decrypt(config.api_key_encrypted)
    base = config.base_url.strip().rstrip("/")
    if not (base and config.model) or urlparse(base).scheme not in ("http", "https"):
        raise AIUnavailable(_("The AI assistant is not configured yet."))

    log = AIRequestLog(
        user=user if getattr(user, "is_authenticated", False) else None,
        username=getattr(user, "username", "") or "",
        campaign=campaign,
        thread=thread,
        purpose=purpose,
        model=config.model,
        request_json=messages,
    )
    started = time.monotonic()
    try:
        reply, usage = llm.chat_completion(
            base, key, config.model, messages, timeout=TIMEOUT_SECONDS
        )
    except llm.LLMError as error:
        log.status = AIRequestLog.Status.ERROR
        log.error = str(error)[:300]
        log.latency_ms = int((time.monotonic() - started) * 1000)
        log.save()
        raise AIUnavailable(_("The AI assistant could not answer right now.")) from None

    sent = sum(len(str(m.get("content", ""))) for m in messages)
    prompt = _int(usage.get("prompt_tokens")) or _estimate_tokens("x" * sent)
    completion = _int(usage.get("completion_tokens")) or _estimate_tokens(reply)
    log.status = AIRequestLog.Status.OK
    log.response_text = reply
    log.prompt_tokens = prompt
    log.completion_tokens = completion
    log.total_tokens = _int(usage.get("total_tokens")) or prompt + completion
    log.latency_ms = int((time.monotonic() - started) * 1000)
    log.save()
    return reply


def _int(value) -> int:
    return value if isinstance(value, int) and value > 0 else 0

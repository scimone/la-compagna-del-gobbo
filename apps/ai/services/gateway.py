"""The one place that calls the model with a campaign's key. Every ask - chat or the settings
page's connection test - is written to `AIRequestLog` (one row per ask, tool rounds included),
with the exact messages and the reply, and on failure the full detail. Never the key."""

import json
import logging
import time
import traceback

from django.utils.translation import gettext as _

from apps.ai.models import AIRequestLog, AISettings
from apps.ai.services import crypto, urlcheck
from apps.frontend import accounts, llm

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120
#: How many times the model may call tools in one ask before it must answer.
MAX_TOOL_ROUNDS = 6


class AIUnavailable(Exception):
    """The model could not be asked or answered. The message is safe to show to the user."""


def _int(value) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def log_failure(
    campaign,
    *,
    user=None,
    thread=None,
    purpose=AIRequestLog.Purpose.CHAT,
    messages=None,
    error: str,
    detail: str = "",
    model: str = "",
    started: float | None = None,
) -> AIRequestLog:
    """Record a failed ask (also one that failed before the model was reached)."""
    entry = AIRequestLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        username=getattr(user, "username", "") or "",
        display_name=accounts.display_name(user)
        if getattr(user, "is_authenticated", False)
        else "",
        campaign=campaign,
        thread=thread,
        purpose=purpose,
        model=model,
        request_json=messages or [],
        status=AIRequestLog.Status.ERROR,
        error=error[:300],
        error_detail=detail[:20000],
        latency_ms=int((time.monotonic() - started) * 1000) if started else 0,
    )
    log.error("AI request %s failed in campaign %s: %s\n%s", entry.pk, campaign.pk, error, detail)
    return entry


def converse(
    messages: list[dict],
    *,
    campaign,
    user=None,
    thread=None,
    purpose: str = AIRequestLog.Purpose.CHAT,
    tools: list[dict] | None = None,
    run_tool=None,
    allow_private: bool = False,
    stream: bool = False,
):
    """Talk to the model; a generator of events: ("ping",), ("delta", text) while the answer is
    written (only with `stream`), ("tool_start", {id, name, args}) and ("tool_end", {id, name, ui})
    around each tool the model calls (`run_tool(name, args)` -> text or (text, ui)), and finally
    ("done", reply). Logs the ask in `AIRequestLog`; raises `AIUnavailable` when it fails."""
    config = AISettings.for_campaign(campaign)
    if purpose != AIRequestLog.Purpose.TEST and not config.enabled:
        raise AIUnavailable(_("The AI assistant is switched off."))
    base = config.base_url.strip().rstrip("/")
    if not (base and config.model):
        raise AIUnavailable(_("The AI assistant is not configured yet."))
    messages = list(messages)
    started = time.monotonic()
    failed = {"campaign": campaign, "user": user, "thread": thread, "purpose": purpose}
    if not (config.allow_private_url or allow_private) and not urlcheck.is_public(base):
        log_failure(
            messages=messages,
            model=config.model,
            started=started,
            error="URL not allowed",
            detail=f"{base} does not resolve to a public address, and an administrator has "
            "not approved it.",
            **failed,
        )
        raise AIUnavailable(_("The AI assistant could not answer right now."))
    key = crypto.decrypt(config.api_key_encrypted)
    use_tools = bool(tools and run_tool and config.use_tools)

    prompt_tokens = completion_tokens = total_tokens = 0
    reply = ""
    try:
        for round_ in range(MAX_TOOL_ROUNDS + 1):
            offered = tools if use_tools and round_ < MAX_TOOL_ROUNDS else None
            message, usage = yield from _model_round(
                stream, base, key, config.model, messages, offered
            )
            prompt_tokens += _int(usage.get("prompt_tokens"))
            completion_tokens += _int(usage.get("completion_tokens"))
            total_tokens += _int(usage.get("total_tokens"))
            calls = message.get("tool_calls") if use_tools else None
            if not calls:
                content = message.get("content")
                if not isinstance(content, str):
                    raise llm.LLMError(
                        "unexpected LLM response",
                        f"reply content is not a string: {content!r}"[:500],
                    )
                reply = content
                break
            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
            for call in calls:
                result = yield from _run_call(call, run_tool)
                messages.append(result)
        else:  # pragma: no cover - the last round passes no tools, so the loop breaks
            raise llm.LLMError("too many tool rounds")
    except llm.LLMError as error:
        log_failure(
            messages=messages,
            model=config.model,
            started=started,
            error=str(error),
            detail=getattr(error, "detail", "") or "",
            **failed,
        )
        raise AIUnavailable(_("The AI assistant could not answer right now.")) from None
    except GeneratorExit:  # the reader went away mid-answer
        log_failure(
            messages=messages,
            model=config.model,
            started=started,
            error="interrupted: the client closed the connection",
            **failed,
        )
        raise
    except AIUnavailable:
        raise
    except Exception:
        log_failure(
            messages=messages,
            model=config.model,
            started=started,
            error="unexpected error",
            detail=traceback.format_exc(),
            **failed,
        )
        raise AIUnavailable(_("The AI assistant could not answer right now.")) from None

    if not prompt_tokens:
        prompt_tokens = max(1, sum(len(str(m.get("content", ""))) for m in messages) // 4)
    if not completion_tokens:
        completion_tokens = max(1, len(reply) // 4)
    AIRequestLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        username=getattr(user, "username", "") or "",
        display_name=accounts.display_name(user)
        if getattr(user, "is_authenticated", False)
        else "",
        campaign=campaign,
        thread=thread,
        purpose=purpose,
        model=config.model,
        request_json=messages,
        response_text=reply,
        status=AIRequestLog.Status.OK,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens or prompt_tokens + completion_tokens,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    yield ("done", reply)


def _model_round(stream, base, key, model, messages, tools):
    """One request to the model -> (message, usage); yields ping/delta events when streaming."""
    if not stream:
        return llm.chat_message(base, key, model, messages, tools=tools, timeout=TIMEOUT_SECONDS)
    message, usage = None, {}
    for kind, value in llm.chat_stream(
        base, key, model, messages, tools=tools, timeout=TIMEOUT_SECONDS
    ):
        if kind == "message":
            message = value
        elif kind == "usage":
            usage = value
        else:
            yield (kind, value)
    if message is None:
        raise llm.LLMError("unexpected LLM response", "the stream ended without a message")
    return message, usage


def ask(messages: list[dict], **kwargs) -> str:
    """`converse`, not streamed, to its final reply."""
    reply = ""
    for kind, value in converse(messages, **kwargs):
        if kind == "done":
            reply = value
    return reply


def _run_call(call, run_tool):
    """Run one tool call of the model, announcing it; returns the `tool` message answering it.
    Errors go back to the model as text (it can recover) and show in the page as a failed step."""
    call_id = call.get("id", "") if isinstance(call, dict) else ""
    function = call.get("function", {}) if isinstance(call, dict) else {}
    name = function.get("name", "")
    arguments = {}
    try:
        arguments = json.loads(function.get("arguments") or "{}")
        if not isinstance(arguments, dict):
            arguments = {}
            raise ValueError("arguments are not an object")
    except ValueError as error:
        yield ("tool_start", {"id": call_id, "name": name, "args": {}})
        result, ui = (
            f"Error: {type(error).__name__}: {error}",
            {"kind": "unknown", "error": str(error)},
        )
    else:
        yield ("tool_start", {"id": call_id, "name": name, "args": arguments})
        try:
            outcome = run_tool(name, arguments)
            result, ui = outcome if isinstance(outcome, tuple) else (outcome, {})
        except Exception as error:
            log.warning("AI tool %s failed: %s", name, error, exc_info=True)
            result = f"Error: {type(error).__name__}: {error}"
            ui = {"kind": "unknown", "error": str(error)}
    yield ("tool_end", {"id": call_id, "name": name, "args": arguments, "ui": ui})
    return {"role": "tool", "tool_call_id": call_id, "content": str(result)}

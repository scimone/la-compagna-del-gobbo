"""The Chat menu: ask the AI assistant about the campaign, with the chats you had before. The
page is server-rendered; a question is a same-origin POST answered as a stream of server-sent
events (`chat_send`): the steps the assistant takes (searching the handbook, reading a page) and
its answer as it is written, both as ready-made HTML."""

import json
import logging
import time

from asgiref.sync import sync_to_async
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.ai.services import chat, context, links
from apps.campaigns.services import membership
from apps.frontend import campaign_context, campaign_views, logbook_markup

log = logging.getLogger(__name__)

#: At most one answer-so-far event per this many seconds (each carries the whole text so far).
TEXT_INTERVAL = 0.06


def _campaign_or_none(request):
    campaign = campaign_context.current(request)
    return campaign if campaign and membership.is_member(request.user, campaign) else None


def _sign_in_redirect(request):
    return redirect(f"{reverse('account')}?next={request.get_full_path()}")


def answer_html(text: str) -> str:
    """An answer as page HTML: only links to real pages survive, the rest is escaped markup."""
    return str(logbook_markup.render(links.clean(text)))


def step_html(step: dict, state: str) -> str:
    more = max(0, int(step.get("count") or 0) - len(step.get("hits") or []))
    return render_to_string(
        "frontend/chat/_step.html", {"step": {**step, "more": more}, "state": state}
    )


def _bubbles(thread) -> list[dict]:
    return [
        {
            "role": m.role,
            "html": answer_html(m.content) if m.role == "assistant" else None,
            "text": m.content,
            "steps": [step_html(s, "error" if s.get("error") else "done") for s in m.activity],
        }
        for m in thread.messages.all()
    ]


def _context(request, campaign, thread):
    return {
        "thread": thread,
        "bubbles": _bubbles(thread),
        "characters": context.characters_for(request.user, campaign),
    }


def chat_page(request, pk=None):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = _campaign_or_none(request)
    if campaign is None:
        return campaign_views.no_campaign_page(request, _("Chat"))
    if not chat.is_available(campaign):
        raise Http404
    if pk is None:
        thread = chat.current_thread(request.user, campaign)
    else:
        thread = chat.get_thread(request.user, campaign, pk)
        if thread is None:
            raise Http404
    response = render(
        request,
        "frontend/chat/chat.html",
        {"page_title": _("Chat"), **_context(request, campaign, thread)},
    )
    add_never_cache_headers(response)
    return response


def chat_history(request):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = _campaign_or_none(request)
    if campaign is None:
        return campaign_views.no_campaign_page(request, _("Chat"))
    if not chat.is_available(campaign):
        raise Http404
    current = chat.current_thread(request.user, campaign)
    response = render(
        request,
        "frontend/chat/history.html",
        {
            "page_title": _("Past chats"),
            "back_url": reverse("chat"),
            "rows": chat.history(request.user, campaign),
            "current": current,
        },
    )
    add_never_cache_headers(response)
    return response


def _thread_from_post(request):
    campaign = _campaign_or_none(request)
    if not request.user.is_authenticated or campaign is None or not chat.is_available(campaign):
        raise Http404
    thread = chat.get_thread(request.user, campaign, request.POST.get("thread") or 0)
    if thread is None:
        raise Http404
    return thread


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _events(thread, text):
    """The chat as server-sent events (a sync generator; `chat_send` makes it async-safe)."""
    yield b": open\n\n"  # response headers and first bytes out at once
    last_text = 0.0
    try:
        for kind, value in chat.send_events(thread, text, stream=True):
            if kind == "ping":
                yield b": ping\n\n"
            elif kind == "text":
                now = time.monotonic()
                if now - last_text >= TEXT_INTERVAL:
                    last_text = now
                    yield _sse("text", {"html": answer_html(value)})
            elif kind == "step_start":
                yield _sse("step_start", {"id": value["id"], "html": step_html(value, "running")})
            elif kind == "step_end":
                state = "error" if value.get("error") else "done"
                yield _sse("step_end", {"id": value["id"], "html": step_html(value, state)})
            elif kind == "done":
                yield _sse("done", {"html": answer_html(value.content)})
    except chat.ChatError as error:
        yield _sse("error", {"message": str(error)})
    except Exception:
        log.exception("chat failed")
        yield _sse("error", {"message": _("Something went wrong. Try again.")})


async def _async_events(thread, text):
    """`_events` for the ASGI server: each step runs in the request's own thread, so a slow model
    blocks nobody else and every event leaves as soon as it exists (a sync generator would be
    collected whole before sending)."""
    events = iter(_events(thread, text))
    end = object()
    step = sync_to_async(next, thread_sensitive=True)
    try:
        while True:
            item = await step(events, end)
            if item is end:
                break
            yield item
    finally:
        await sync_to_async(events.close, thread_sensitive=True)()


@require_POST
def chat_send(request):
    thread = _thread_from_post(request)
    response = StreamingHttpResponse(
        _async_events(thread, request.POST.get("message", "")),
        content_type="text/event-stream; charset=utf-8",
    )
    # Streaming only works if nothing between here and the browser holds the bytes back:
    response["Cache-Control"] = "no-cache, no-transform"  # Cloudflare: don't rewrite/compress
    response["Content-Encoding"] = "identity"  # and GZipMiddleware: don't compress
    response["X-Accel-Buffering"] = "no"  # nginx-style proxies: don't buffer
    return response


@require_POST
def chat_new(request):
    campaign = _campaign_or_none(request)
    if not request.user.is_authenticated or campaign is None or not chat.is_available(campaign):
        raise Http404
    chat.new_thread(request.user, campaign)
    return redirect("chat")


@require_POST
def chat_delete(request, pk):
    campaign = _campaign_or_none(request)
    if not request.user.is_authenticated or campaign is None or not chat.is_available(campaign):
        raise Http404
    thread = chat.get_thread(request.user, campaign, pk)
    if thread is None:
        raise Http404
    thread.delete()
    return redirect("chat-history")


@require_POST
def chat_character(request):
    thread = _thread_from_post(request)
    try:
        chat.pick_character(thread, request.POST.get("character", ""))
    except chat.ChatError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return HttpResponse(status=204)

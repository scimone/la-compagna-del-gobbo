"""The Chat menu: ask the AI assistant about the campaign. The page is server-rendered; asking a
question is a same-origin JSON POST (`chat_send`) answered with the reply as HTML."""

import logging

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.ai.services import chat, context
from apps.campaigns.services import membership
from apps.frontend import campaign_context, campaign_views, logbook_markup

log = logging.getLogger(__name__)


def _campaign_or_none(request):
    campaign = campaign_context.current(request)
    return campaign if campaign and membership.is_member(request.user, campaign) else None


def _sign_in_redirect(request):
    return redirect(f"{reverse('account')}?next={request.get_full_path()}")


def _bubbles(thread) -> list[dict]:
    return [
        {
            "role": m.role,
            "html": logbook_markup.render(m.content) if m.role == "assistant" else None,
            "text": m.content,
        }
        for m in thread.messages.all()
    ]


def chat_page(request):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = _campaign_or_none(request)
    if campaign is None:
        return campaign_views.no_campaign_page(request, _("Chat"))
    if not chat.is_available():
        raise Http404
    thread = chat.current_thread(request.user, campaign)
    response = render(
        request,
        "frontend/chat/chat.html",
        {
            "page_title": _("Chat"),
            "thread": thread,
            "bubbles": _bubbles(thread),
            "characters": context.characters_for(request.user, campaign),
        },
    )
    add_never_cache_headers(response)
    return response


def _thread_of(request):
    campaign = _campaign_or_none(request)
    if not request.user.is_authenticated or campaign is None:
        raise Http404
    if not chat.is_available():
        raise Http404
    return chat.current_thread(request.user, campaign)


@require_POST
def chat_send(request):
    thread = _thread_of(request)
    try:
        answer = chat.send(thread, request.POST.get("message", ""))
    except chat.ChatError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except Exception:
        log.exception("chat failed")
        return JsonResponse({"error": _("Something went wrong. Try again.")}, status=500)
    return JsonResponse({"ok": True, "html": str(logbook_markup.render(answer.content))})


@require_POST
def chat_new(request):
    campaign = _campaign_or_none(request)
    if not request.user.is_authenticated or campaign is None or not chat.is_available():
        raise Http404
    chat.new_thread(request.user, campaign)
    return redirect("chat")


@require_POST
def chat_character(request):
    thread = _thread_of(request)
    try:
        chat.pick_character(thread, request.POST.get("character", ""))
    except chat.ChatError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"ok": True})

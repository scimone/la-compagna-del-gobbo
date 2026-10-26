"""The chat itself: a user's thread in a campaign, rate limits, and one question -> one answer."""

import time
import traceback
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai.models import AIRequestLog, AISettings, ChatMessage, ChatThread
from apps.ai.services import context, gateway, links, tools, usage
from apps.campaigns.services import membership
from apps.characters.models import Character
from apps.characters.services import access

MAX_QUESTION_CHARS = 2000
#: How many of the thread's latest messages go back to the model with a new question.
HISTORY_MESSAGES = 20
MAX_PER_MINUTE = 6


class ChatError(Exception):
    """A question that can't be answered; the message is safe to show to the user."""


def is_available(campaign) -> bool:
    return campaign is not None and AISettings.for_campaign(campaign).is_ready


def current_thread(user, campaign) -> ChatThread:
    """The user's latest thread in `campaign`, or a new one (with their own character, if any)."""
    thread = ChatThread.objects.filter(user=user, campaign=campaign).first()
    return thread or new_thread(user, campaign)


def new_thread(user, campaign) -> ChatThread:
    """A fresh chat - or the user's latest one if that is still empty."""
    latest = ChatThread.objects.filter(user=user, campaign=campaign).first()
    if latest is not None and not latest.messages.exists():
        return latest
    mine = (
        Character.objects.filter(campaign=campaign, owner=user, status=Character.STATUS_COMPLETE)
        .order_by("name")
        .first()
    )
    return ChatThread.objects.create(user=user, campaign=campaign, character=mine)


def pick_character(thread: ChatThread, character_id) -> None:
    """Say who the user plays in this thread (any character they may see, or nobody)."""
    character = None
    if character_id:
        character = Character.objects.filter(
            pk=character_id, campaign=thread.campaign, status=Character.STATUS_COMPLETE
        ).first()
        if character is None or not access.can_view(thread.user, character):
            raise ChatError(_("That character is not available."))
    thread.character = character
    thread.save(update_fields=["character"])


def _check_limits(user, campaign) -> None:
    recent = AIRequestLog.objects.filter(
        user=user,
        campaign=campaign,
        purpose=AIRequestLog.Purpose.CHAT,
        created_at__gte=timezone.now() - timedelta(minutes=1),
    ).count()
    if recent >= MAX_PER_MINUTE:
        raise ChatError(_("Too many questions in a row - wait a moment."))
    cap = AISettings.for_campaign(campaign).daily_message_cap
    if cap and usage.messages_today(user, campaign) >= cap:
        raise ChatError(_("You have reached today's limit of questions."))


def _chain(message: ChatMessage | None) -> list[ChatMessage]:
    """`message` and everything it follows, first to last."""
    messages = []
    while message is not None:
        messages.append(message)
        message = message.parent
    return messages[::-1]


def path(thread: ChatThread) -> list[ChatMessage]:
    """The messages of the version shown, first to last."""
    return _chain(thread.head)


def _deepest(message: ChatMessage) -> ChatMessage:
    """The last message of the newest chain of follow-ups below `message` (or itself)."""
    while True:
        child = message.children.order_by("-pk").first()
        if child is None:
            return message
        message = child


def versions(message: ChatMessage) -> dict:
    """Where `message` stands among its alternatives (the versions made by editing/resending):
    `{"index", "total", "prev", "next"}` (ids), `total` 1 when there is only one."""
    siblings = list(
        ChatMessage.objects.filter(thread=message.thread, parent=message.parent, role=message.role)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    index = siblings.index(message.pk)
    return {
        "index": index + 1,
        "total": len(siblings),
        "prev": siblings[index - 1] if index > 0 else None,
        "next": siblings[index + 1] if index + 1 < len(siblings) else None,
    }


def timeline(thread: ChatThread) -> list[dict]:
    """What the chat page shows: `{message, versions}` for each message of the shown version."""
    return [
        {"message": m, "versions": versions(m) if m.role == ChatMessage.Role.USER else None}
        for m in path(thread)
    ]


def switch_version(thread: ChatThread, message_id) -> None:
    """Show another version: make `message_id` (an alternative of a message of this chat) the
    thread's version, followed by its newest follow-ups."""
    message = ChatMessage.objects.filter(pk=message_id or 0, thread=thread).first()
    if message is None:
        raise ChatError(_("That message is not in this chat."))
    thread.head = _deepest(message)
    thread.save(update_fields=["head"])


def _history(parent: ChatMessage | None) -> list[dict]:
    """The earlier turns for the model: the version leading to `parent`, empty ones dropped and
    neighbours of one role joined (a cut-short answer can leave two questions in a row)."""
    turns = []
    for message in _chain(parent)[-HISTORY_MESSAGES:]:
        if not message.content.strip():
            continue
        if turns and turns[-1]["role"] == message.role:
            turns[-1]["content"] += "\n\n" + message.content
        else:
            turns.append({"role": message.role, "content": message.content})
    return turns


def prepare(
    thread: ChatThread, text: str, replace=None
) -> tuple[str, ChatMessage | None, list[dict]]:
    """Validate a question and build what the model gets (context + history + question).
    `replace` is a question of this chat being edited or resent: the new one becomes its
    alternative, answering from the same earlier turns. Returns (text, the message the new
    question follows, messages); raises `ChatError` when it is refused."""
    parent = thread.head
    if replace is not None:
        original = ChatMessage.objects.filter(
            pk=replace, thread=thread, role=ChatMessage.Role.USER
        ).first()
        if original is None:
            raise ChatError(_("That message is not in this chat."))
        parent = original.parent
        text = text.strip() or original.content
    text = text.strip()
    if not text:
        raise ChatError(_("Write a question first."))
    if len(text) > MAX_QUESTION_CHARS:
        raise ChatError(_("The question is too long."))
    user, campaign = thread.user, thread.campaign
    if not membership.is_member(user, campaign):
        raise ChatError(_("You are not in this campaign."))
    if not is_available(campaign):
        raise ChatError(_("The AI assistant is not available."))
    _check_limits(user, campaign)

    config = AISettings.for_campaign(campaign)
    started = time.monotonic()
    messages = [{"role": "user", "content": text}]
    try:
        messages = [
            {"role": "system", "content": context.build(user, campaign, thread.character)},
            *_history(parent),
            {"role": "user", "content": text},
        ]
    except Exception:
        gateway.log_failure(
            campaign,
            user=user,
            thread=thread,
            messages=messages,
            model=config.model,
            started=started,
            error="could not build the context",
            detail=traceback.format_exc(),
        )
        raise ChatError(_("Something went wrong. Try again.")) from None
    return text, parent, messages


def _store(thread, parent, text, reply, steps, *, partial=False) -> ChatMessage:
    """Save a question and its answer as the newest version, and show it."""
    question = ChatMessage.objects.create(
        thread=thread, parent=parent, role=ChatMessage.Role.USER, content=text
    )
    answer = ChatMessage.objects.create(
        thread=thread,
        parent=question,
        role=ChatMessage.Role.ASSISTANT,
        content=links.clean(reply.strip()),
        activity=steps,
        partial=partial,
    )
    thread.head = answer
    thread.save(update_fields=["head"])
    return answer


def send_events(thread: ChatThread, text: str, *, stream: bool = True, replace=None):
    """Ask `text` in `thread`. A generator of events for the page: ("ping",), ("text", the
    answer so far) while it is written, ("step_start", step) / ("step_end", step) around each
    thing the assistant looks up, and finally ("done", the stored answer `ChatMessage`). The
    question and answer are stored when it completes - or, if the reader goes away mid-answer,
    with what had been written so far (marked `partial`). Raises `ChatError`."""
    text, parent, messages = prepare(thread, text, replace)
    steps: list[dict] = []
    written = ""
    reply = None
    try:
        for kind, value in gateway.converse(
            messages,
            campaign=thread.campaign,
            user=thread.user,
            thread=thread,
            tools=tools.TOOLS,
            run_tool=tools.runner(thread.user, thread.campaign),
            stream=stream,
        ):
            if kind == "delta":
                written += value
                yield ("text", written)
            elif kind == "ping":
                yield ("ping", None)
            elif kind == "tool_start":
                written = ""  # whatever it said before looking something up is not the answer
                yield ("step_start", _step(value))
            elif kind == "tool_end":
                step = _step(value) | value["ui"]
                steps.append(step)
                yield ("step_end", step)
            elif kind == "done":
                reply = value
    except gateway.AIUnavailable as error:
        raise ChatError(str(error)) from None
    except GeneratorExit:
        _store(thread, parent, text, written, steps, partial=True)
        raise
    yield ("done", _store(thread, parent, text, reply, steps))


STEP_KINDS = {
    "search_handbook": "search",
    "read_page": "read",
    "get_character_details": "character",
    "search_logbook": "logbook_search",
    "read_logbook_entry": "logbook_read",
}


def _step(event: dict) -> dict:
    """What the page needs to show a tool call: its id, kind and what was asked for."""
    args = event.get("args") or {}
    query = args.get("query") or args.get("path") or args.get("character") or args.get("id") or ""
    return {
        "id": event.get("id", ""),
        "kind": STEP_KINDS.get(event.get("name"), "search"),
        "query": str(query),
    }


def send(thread: ChatThread, text: str, *, stream: bool = False, replace=None) -> ChatMessage:
    """`send_events` to the end: the stored answer."""
    answer = None
    for kind, value in send_events(thread, text, stream=stream, replace=replace):
        if kind == "done":
            answer = value
    return answer


# --- Past chats --------------------------------------------------------------------------------


def get_thread(user, campaign, pk) -> ChatThread | None:
    return ChatThread.objects.filter(pk=pk, user=user, campaign=campaign).first()


def history(user, campaign) -> list[dict]:
    """The user's chats in this campaign that hold at least one message, newest activity first:
    `{thread, title, last, count}` where `title` is the first question of the version shown."""
    rows = []
    threads = (
        ChatThread.objects.filter(user=user, campaign=campaign)
        .select_related("character", "head")
        .prefetch_related("messages")
    )
    for thread in threads:
        everything = list(thread.messages.all())
        if not everything:
            continue
        shown = path(thread) or everything[:1]
        first_question = next((m for m in shown if m.role == ChatMessage.Role.USER), shown[0])
        rows.append(
            {
                "thread": thread,
                "title": first_question.content,
                "last": max(m.created_at for m in everything),
                "count": len(shown),
            }
        )
    rows.sort(key=lambda r: r["last"], reverse=True)
    return rows

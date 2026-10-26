"""The chat itself: a user's thread in a campaign, rate limits, and one question -> one answer."""

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai.models import AIRequestLog, AISettings, ChatMessage, ChatThread
from apps.ai.services import context, gateway, usage
from apps.campaigns.services import membership
from apps.characters.models import Character
from apps.characters.services import access

MAX_QUESTION_CHARS = 2000
#: How many of the thread's latest messages go back to the model with a new question.
HISTORY_MESSAGES = 20
MAX_PER_MINUTE = 6


class ChatError(Exception):
    """A question that can't be answered; the message is safe to show to the user."""


def is_available() -> bool:
    return AISettings.load().is_ready


def current_thread(user, campaign) -> ChatThread:
    """The user's latest thread in `campaign`, or a new one (with their own character, if any)."""
    thread = ChatThread.objects.filter(user=user, campaign=campaign).first()
    return thread or new_thread(user, campaign)


def new_thread(user, campaign) -> ChatThread:
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


def _check_limits(user) -> None:
    recent = AIRequestLog.objects.filter(
        user=user,
        purpose=AIRequestLog.Purpose.CHAT,
        created_at__gte=timezone.now() - timedelta(minutes=1),
    ).count()
    if recent >= MAX_PER_MINUTE:
        raise ChatError(_("Too many questions in a row - wait a moment."))
    cap = AISettings.load().daily_message_cap
    if cap and usage.messages_today(user) >= cap:
        raise ChatError(_("You have reached today's limit of questions."))


def send(thread: ChatThread, text: str) -> ChatMessage:
    """Ask `text` in `thread`; stores the question and the answer and returns the answer. Raises
    `ChatError` (nothing stored) when the question is refused or the model can't answer."""
    text = text.strip()
    if not text:
        raise ChatError(_("Write a question first."))
    if len(text) > MAX_QUESTION_CHARS:
        raise ChatError(_("The question is too long."))
    user, campaign = thread.user, thread.campaign
    if not membership.is_member(user, campaign):
        raise ChatError(_("You are not in this campaign."))
    if not is_available():
        raise ChatError(_("The AI assistant is not available."))
    _check_limits(user)

    history = list(thread.messages.order_by("-created_at", "-pk")[:HISTORY_MESSAGES])[::-1]
    messages = [
        {"role": "system", "content": context.build(user, campaign, thread.character)},
        *({"role": m.role, "content": m.content} for m in history),
        {"role": "user", "content": text},
    ]
    try:
        reply = gateway.ask(messages, user=user, campaign=campaign, thread=thread)
    except gateway.AIUnavailable as error:
        raise ChatError(str(error)) from None
    ChatMessage.objects.create(thread=thread, role=ChatMessage.Role.USER, content=text)
    return ChatMessage.objects.create(
        thread=thread, role=ChatMessage.Role.ASSISTANT, content=reply.strip() or "…"
    )

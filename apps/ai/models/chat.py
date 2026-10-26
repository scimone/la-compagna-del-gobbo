from django.conf import settings
from django.db import models


class ChatThread(models.Model):
    """One conversation of a user in a campaign; `character` is who they say they are playing."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_threads"
    )
    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.CASCADE, related_name="chat_threads"
    )
    character = models.ForeignKey(
        "characters.Character", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: The last message of the version of the chat being shown (see `ChatMessage.parent`).
    head = models.ForeignKey(
        "ai.ChatMessage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Chat {self.pk} of {self.user_id} in {self.campaign_id}"


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name="messages")
    #: The message this one follows. Editing or resending a question adds a *sibling* (same
    #: parent) with its own follow-ups, so a chat is a tree and `ChatThread.head` picks the
    #: version shown; the user flips between siblings.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    #: What the assistant looked up while answering (assistant messages): a list of
    #: `{"kind": "search" | "read", "query" | "title", "url", "count", "hits": [...], "error"}`.
    activity = models.JSONField(default=list, blank=True)
    #: The answer was cut short (the page was closed mid-answer): what had been written is kept.
    partial = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:40]}"

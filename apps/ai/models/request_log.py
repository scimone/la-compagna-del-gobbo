from django.conf import settings
from django.db import models


class AIRequestLog(models.Model):
    """Every call made with the API key, success or failure: the exact messages sent (campaign
    context included) and the reply. The key itself is never stored here."""

    class Purpose(models.TextChoices):
        CHAT = "chat"
        TEST = "test"

    class Status(models.TextChoices):
        OK = "ok"
        ERROR = "error"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    username = models.CharField(max_length=150, blank=True)
    campaign = models.ForeignKey(
        "campaigns.Campaign", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    thread = models.ForeignKey(
        "ai.ChatThread", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.CHAT)
    model = models.CharField(max_length=200, blank=True)
    request_json = models.JSONField(default=list)
    response_text = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.CharField(max_length=300, blank=True)
    #: Everything known about a failure (status, response body, traceback) - never the key.
    error_detail = models.TextField(blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.username or '-'} {self.created_at:%Y-%m-%d %H:%M} {self.status}"

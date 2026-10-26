from django.db import models


class AISettings(models.Model):
    """The one row of AI configuration an administrator edits in the admin panel (`load()` gets
    it). The API key is stored encrypted (`services/crypto.py`) and is never shown again."""

    enabled = models.BooleanField(default=False)
    base_url = models.CharField(
        max_length=300, blank=True, help_text="OpenAI-compatible, without /chat/completions"
    )
    model = models.CharField(max_length=200, blank=True)
    api_key_encrypted = models.TextField(blank=True)
    system_prompt_extra = models.TextField(blank=True)
    max_context_chars = models.PositiveIntegerField(default=60000)
    daily_message_cap = models.PositiveIntegerField(default=100, help_text="Per user; 0 = no cap")
    log_retention_days = models.PositiveIntegerField(default=90, help_text="0 = keep forever")

    class Meta:
        verbose_name_plural = "AI settings"

    def __str__(self) -> str:
        return "AI settings"

    @classmethod
    def load(cls) -> "AISettings":
        return cls.objects.get_or_create(pk=1)[0]

    @property
    def has_key(self) -> bool:
        return bool(self.api_key_encrypted)

    @property
    def is_ready(self) -> bool:
        return bool(self.enabled and self.base_url and self.model)

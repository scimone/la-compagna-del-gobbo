from django.db import models


class AISettings(models.Model):
    """One campaign's AI configuration, edited by its DM (or an administrator); a campaign never
    inherits another's. `for_campaign()` gets (or creates) the row. The API key is stored
    encrypted (`services/crypto.py`) and is never shown again."""

    campaign = models.OneToOneField(
        "campaigns.Campaign", on_delete=models.CASCADE, related_name="ai_settings"
    )
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
    #: Let the model search and read the handbook (OpenAI-style function calling). Switch off for
    #: a provider/model that rejects `tools`.
    use_tools = models.BooleanField(default=True)
    #: Set when an administrator saved the URL: only then may it point at a private address
    #: (a DM's URL must be a public one, so the server can't be aimed at its own network).
    allow_private_url = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "AI settings"

    def __str__(self) -> str:
        return f"AI settings of campaign {self.campaign_id}"

    @classmethod
    def for_campaign(cls, campaign) -> "AISettings":
        return cls.objects.get_or_create(campaign=campaign)[0]

    @property
    def has_key(self) -> bool:
        return bool(self.api_key_encrypted)

    @property
    def is_ready(self) -> bool:
        return bool(self.enabled and self.base_url and self.model)

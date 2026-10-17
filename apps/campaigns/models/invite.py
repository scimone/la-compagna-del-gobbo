from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

INVITE_LIFETIME = timedelta(days=183)  # about six months


def default_expiry():
    return timezone.now() + INVITE_LIFETIME


class CampaignInvite(models.Model):
    """An invitation to a campaign, addressed to an e-mail (stored lower-cased). It is matched
    against the verified e-mail of whoever signs in, so the invited person sees it as soon as
    they open the app. Open = neither accepted nor revoked (declining counts as revoking)."""

    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.CASCADE, related_name="invites"
    )
    email = models.EmailField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "email"],
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="one_open_invite_per_email",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.email} -> {self.campaign_id}"

    @property
    def is_open(self) -> bool:
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )

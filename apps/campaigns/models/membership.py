from django.conf import settings
from django.db import models


class CampaignMembership(models.Model):
    """One account's place in one campaign. Exactly one membership per campaign is the `dm`
    (enforced by the database); the DM hands the role over with `lifecycle.transfer_dm`."""

    DM = "dm"
    PLAYER = "player"
    ROLE_CHOICES = [(DM, "DM"), (PLAYER, "Player")]

    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="campaign_memberships"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=PLAYER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["campaign", "user"], name="unique_campaign_member"),
            models.UniqueConstraint(
                fields=["campaign"],
                condition=models.Q(role="dm"),
                name="one_dm_per_campaign",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.campaign_id} ({self.role})"

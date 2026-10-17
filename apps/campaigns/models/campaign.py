import secrets

from django.conf import settings
from django.db import models


def new_join_code() -> str:
    return secrets.token_urlsafe(16)


class Campaign(models.Model):
    """A group of people playing together: the one scope of characters and of the Logbook. Only
    its members (and administrators) see anything inside it.

    `join_code` is the secret in the campaign's join link; the DM can switch the link off
    (`join_enabled`) or replace the code. It is a single free-text `name` (no translation).
    """

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    join_code = models.CharField(max_length=64, unique=True, default=new_join_code)
    join_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self) -> str:
        return self.name

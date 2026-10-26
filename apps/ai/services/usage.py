"""What the campaign pages show about AI use: totals, a table per user and a series per day, all
computed from `AIRequestLog` rows of one campaign. Plus the retention clean-up."""

from datetime import timedelta

from django.db.models import Avg, Count, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.ai.models import AIRequestLog, AISettings

#: period key -> how far back it reaches (None = everything)
PERIODS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}
DEFAULT_PERIOD = "7d"


def period_queryset(campaign, period: str):
    queryset = AIRequestLog.objects.filter(campaign=campaign)
    span = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])
    return queryset.filter(created_at__gte=timezone.now() - span) if span else queryset


def totals(queryset) -> dict:
    return queryset.aggregate(
        requests=Count("pk"),
        errors=Count("pk", filter=Q(status=AIRequestLog.Status.ERROR)),
        prompt_tokens=Sum("prompt_tokens", default=0),
        completion_tokens=Sum("completion_tokens", default=0),
        tokens=Sum("total_tokens", default=0),
        latency_ms=Avg("latency_ms", default=0),
    )


def per_user(queryset) -> list[dict]:
    return list(
        queryset.values("username")
        .annotate(
            requests=Count("pk"),
            errors=Count("pk", filter=Q(status=AIRequestLog.Status.ERROR)),
            prompt_tokens=Sum("prompt_tokens", default=0),
            completion_tokens=Sum("completion_tokens", default=0),
            tokens=Sum("total_tokens", default=0),
            last_used=Max("created_at"),
        )
        .order_by("-tokens", "username")
    )


def per_day(queryset, tz) -> list[dict]:
    """One row per day with a `percent` bar width relative to the busiest day."""
    rows = list(
        queryset.annotate(day=TruncDate("created_at", tzinfo=tz))
        .values("day")
        .annotate(requests=Count("pk"), tokens=Sum("total_tokens", default=0))
        .order_by("day")
    )
    most = max((row["tokens"] for row in rows), default=0) or 1
    for row in rows:
        row["percent"] = round(100 * row["tokens"] / most)
    return rows


def messages_today(user, campaign) -> int:
    """Chat questions `user` has sent in `campaign` since local midnight (the daily cap)."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return AIRequestLog.objects.filter(
        user=user, campaign=campaign, purpose=AIRequestLog.Purpose.CHAT, created_at__gte=start
    ).count()


def prune_logs() -> int:
    """Delete log rows older than each campaign's retention setting; returns how many went."""
    deleted = 0
    for config in AISettings.objects.filter(log_retention_days__gt=0):
        cutoff = timezone.now() - timedelta(days=config.log_retention_days)
        deleted += AIRequestLog.objects.filter(
            campaign_id=config.campaign_id, created_at__lt=cutoff
        ).delete()[0]
    return deleted

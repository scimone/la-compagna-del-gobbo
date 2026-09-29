"""Who used what: a summary of the `Interaction` table, and pruning of old rows."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Max
from django.utils import timezone

from apps.frontend.models import Interaction


class Command(BaseCommand):
    help = "Print who did what in the last N days (default 30); --prune deletes older rows."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--prune", action="store_true", help="Delete rows older than --days.")

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(days=options["days"])
        if options["prune"]:
            deleted, _ = Interaction.objects.filter(created_at__lt=since).delete()
            self.stdout.write(f"Deleted {deleted} interactions older than {options['days']} days.")
            return
        rows = Interaction.objects.filter(created_at__gte=since)
        self.stdout.write(f"{rows.count()} interactions since {since:%Y-%m-%d}\n")
        self.stdout.write("Per user (views / actions, last seen):")
        for row in (
            rows.values("username")
            .annotate(last=Max("created_at"), total=Count("id"))
            .order_by("-total")
        ):
            views = rows.filter(username=row["username"], kind="view").count()
            self.stdout.write(
                f"  {row['username'] or '(not signed in)':<20} {views:>5} / "
                f"{row['total'] - views:<5} {row['last']:%Y-%m-%d %H:%M}"
            )
        self.stdout.write("\nMost used pages:")
        for row in (
            rows.filter(kind="view").values("route").annotate(n=Count("id")).order_by("-n")[:15]
        ):
            self.stdout.write(f"  {row['n']:>5}  {row['route'] or '(unnamed)'}")
        self.stdout.write("\nActions:")
        for row in (
            rows.filter(kind="action")
            .values("route", "action")
            .annotate(n=Count("id"))
            .order_by("-n")[:15]
        ):
            self.stdout.write(f"  {row['n']:>5}  {row['route']} {row['action']}".rstrip())

from django.core.management.base import BaseCommand

from apps.ai.services import usage


class Command(BaseCommand):
    help = "Delete AI request logs older than the retention set in the admin panel."

    def handle(self, *args, **options):
        self.stdout.write(f"Deleted {usage.prune_logs()} log rows")

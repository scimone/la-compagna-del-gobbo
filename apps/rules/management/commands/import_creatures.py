from django.core.management.base import BaseCommand
from django.db import transaction

from apps.rules.management.commands.import_rules_data import Command as RulesImport
from apps.rules.models import Creature


class Command(BaseCommand):
    help = (
        "Wipe and reload only the creature stat blocks (db/creatures.json). Unlike "
        "import_rules_data it leaves every other rules table alone, so it works on a database "
        "that already holds characters."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        Creature.objects.all().delete()
        importer = RulesImport(stdout=self.stdout, stderr=self.stderr)
        importer._import_creatures()

from django.core.management.base import BaseCommand, CommandError

from apps.rules.handbook_source import TranslationDataError, load_handbook
from apps.rules.models import HandbookSection
from apps.rules.translation_sync import sync_catalogs


class Command(BaseCommand):
    help = (
        "Sync the translated models with db/ and db/it/: the handbook (English and Italian, "
        "creating/updating/deleting only its rows) and the Italian columns of the other "
        "catalogs. Unlike import_rules_data this "
        "wipes nothing else, so it's safe to re-run whenever a translation file or an omit list "
        "changes, including once Character rows reference the rules tables."
    )

    def handle(self, *args, **options):
        try:
            english, italian = load_handbook()
            sync_catalogs(lambda message: self.stdout.write(message))
        except TranslationDataError as exc:
            raise CommandError(str(exc)) from exc

        # Rows dropped from the source (e.g. a section with no Italian text yet) leave the
        # database too, so a re-run always leaves exactly what an import_rules_data would.
        deleted, _ = HandbookSection.objects.exclude(pk__in=[row["id"] for row in english]).delete()
        for row in english:
            translated = italian.get(row["id"], {})
            HandbookSection.objects.update_or_create(
                pk=row["id"],
                defaults={
                    "page": row["page"],
                    "name_en": row["name"],
                    "entries_en": row["entries"],
                    "name_it": translated.get("name"),
                    "entries_it": translated.get("entries"),
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"HandbookSection: {len(english)} sections ({len(italian)} with Italian text), "
                f"{deleted} removed."
            )
        )

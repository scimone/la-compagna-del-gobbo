from django.core.management.base import BaseCommand, CommandError

from apps.rules.handbook_source import TranslationDataError, load_handbook
from apps.rules.models import HandbookChapter, HandbookSection
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
            chapters, english, italian = load_handbook()
            sync_catalogs(lambda message: self.stdout.write(message))
        except TranslationDataError as exc:
            raise CommandError(str(exc)) from exc

        for chapter in chapters:
            HandbookChapter.objects.update_or_create(
                pk=chapter["id"],
                defaults={"name_en": chapter["name"], "name_it": chapter["name_it"]},
            )

        # Rows dropped from the source (e.g. a section with no Italian text yet) leave the
        # database too, so a re-run always leaves exactly what an import_rules_data would.
        deleted, _ = HandbookSection.objects.exclude(pk__in=[row["id"] for row in english]).delete()
        for row in english:
            translated = italian.get(row["id"], {})
            HandbookSection.objects.update_or_create(
                pk=row["id"],
                defaults={
                    "chapter_id": row["chapter"],
                    "page": row["page"],
                    "name_en": row["name"],
                    "entries_en": row["entries"],
                    "name_it": translated.get("name"),
                    "entries_it": translated.get("entries"),
                    "self_translated_fields": translated.get("self_translated_fields", []),
                },
            )
        HandbookChapter.objects.exclude(pk__in=[chapter["id"] for chapter in chapters]).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"HandbookChapter: {len(chapters)}; HandbookSection: {len(english)} sections "
                f"({len(italian)} with Italian text), {deleted} removed."
            )
        )

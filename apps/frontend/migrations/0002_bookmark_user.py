import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def drop_unowned_bookmarks(apps, schema_editor):
    # Bookmarks used to be global (no owner). With per-user bookmarks there's no one to hand
    # them to, and the column below is NOT NULL.
    apps.get_model("frontend", "Bookmark").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("frontend", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(drop_unowned_bookmarks, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="bookmark", name="unique_bookmark"),
        migrations.AddField(
            model_name="bookmark",
            name="user",
            field=models.ForeignKey(
                default=None,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="bookmarks",
                to=settings.AUTH_USER_MODEL,
            ),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="bookmark",
            constraint=models.UniqueConstraint(
                fields=("user", "kind", "object_id"), name="unique_user_bookmark"
            ),
        ),
    ]

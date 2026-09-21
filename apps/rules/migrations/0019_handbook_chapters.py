import django.db.models.deletion
from django.db import migrations, models


def put_existing_sections_in_playing_the_game(apps, schema_editor):
    # Until now every row belonged to the source's one chapter, "Playing the Game" (id "007").
    # Backfill it so the rows already in the table keep working before the next import.
    HandbookChapter = apps.get_model("rules", "HandbookChapter")
    HandbookSection = apps.get_model("rules", "HandbookSection")
    if not HandbookSection.objects.exists():
        return
    chapter = HandbookChapter.objects.create(
        id="007", name="Playing the Game", name_en="Playing the Game", name_it="Come si gioca"
    )
    HandbookSection.objects.update(chapter=chapter)


class Migration(migrations.Migration):

    dependencies = [
        ('rules', '0018_builder_data_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='HandbookChapter',
            fields=[
                ('id', models.SlugField(max_length=100, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('name_en', models.CharField(max_length=200, null=True)),
                ('name_it', models.CharField(max_length=200, null=True)),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.AlterModelOptions(
            name='handbooksection',
            options={'ordering': ['chapter_id', 'id']},
        ),
        migrations.AddField(
            model_name='handbooksection',
            name='self_translated_fields',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='handbooksection',
            name='chapter',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sections', to='rules.handbookchapter'),
        ),
        migrations.RunPython(put_existing_sections_in_playing_the_game, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='handbooksection',
            name='chapter',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sections', to='rules.handbookchapter'),
        ),
    ]

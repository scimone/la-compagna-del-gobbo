"""The gallery: extra pictures besides the portrait."""

import pytest

from apps.characters.models import Character
from apps.characters.services import portrait
from apps.characters.tests.test_portrait import picture


@pytest.fixture
def hero(db, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return Character.objects.create(name="Hero")


def test_pictures_are_added_and_removed_with_their_files(hero, tmp_path):
    first = portrait.add_picture(hero, picture())
    portrait.add_picture(hero, picture())
    assert hero.pictures.count() == 2 and (tmp_path / first.image.name).exists()

    portrait.remove_picture(hero, first.pk)
    assert hero.pictures.count() == 1 and not (tmp_path / first.image.name).exists()
    portrait.remove_picture(hero, first.pk)  # already gone: ignored


def test_a_non_picture_is_refused_and_the_gallery_has_a_limit(hero, monkeypatch):
    monkeypatch.setattr(portrait, "MAX_GALLERY", 1)
    portrait.add_picture(hero, picture())
    with pytest.raises(ValueError):
        portrait.add_picture(hero, picture())
    assert hero.pictures.count() == 1

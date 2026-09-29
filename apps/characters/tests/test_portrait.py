"""The portrait service: what an upload becomes before it is stored."""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.characters.models import Character
from apps.characters.services import portrait


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def hero(db):
    return Character.objects.create(name="Hero")


def picture(size=(100, 100), fmt="PNG", **save):
    out = BytesIO()
    Image.new("RGB", size, "teal").save(out, fmt, **save)
    return SimpleUploadedFile(f"x.{fmt.lower()}", out.getvalue())


def stored(hero) -> Image.Image:
    with hero.portrait.open("rb") as file:
        image = Image.open(BytesIO(file.read()))
        image.load()
    return image


def test_an_upload_is_stored_as_a_shrunk_webp(hero, media):
    portrait.set_portrait(hero, picture((2400, 1800), "JPEG"))

    hero.refresh_from_db()
    image = stored(hero)
    assert image.format == "WEBP" and image.width <= 1024 and image.height <= 1024
    assert image.width / image.height == pytest.approx(4 / 3, abs=0.01)  # same shape, just smaller
    assert hero.portrait.name.startswith("portraits/") and (media / hero.portrait.name).exists()


def test_a_small_picture_is_not_blown_up(hero):
    portrait.set_portrait(hero, picture((80, 120)))

    assert stored(hero).size == (80, 120)


def test_a_phone_photos_rotation_is_applied(hero):
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees to view"
    portrait.set_portrait(hero, picture((100, 50), "JPEG", exif=exif))

    assert stored(hero).size == (50, 100)


def test_a_new_picture_replaces_the_old_file(hero, media):
    portrait.set_portrait(hero, picture())
    first = hero.portrait.name

    portrait.set_portrait(hero, picture())

    assert hero.portrait.name != first
    assert not (media / first).exists() and (media / hero.portrait.name).exists()


def test_what_is_not_a_picture_is_refused_and_the_old_one_kept(hero, media):
    portrait.set_portrait(hero, picture())
    kept = hero.portrait.name

    for bad in (
        SimpleUploadedFile("x.png", b"<svg onload=alert(1)></svg>"),
        SimpleUploadedFile("x.png", b""),
        picture(fmt="BMP"),  # a real picture, but not one of the accepted kinds
    ):
        with pytest.raises(ValueError):
            portrait.set_portrait(hero, bad)
    hero.refresh_from_db()
    assert hero.portrait.name == kept and (media / kept).exists()


def test_an_upload_over_the_size_limit_is_refused(hero, monkeypatch):
    monkeypatch.setattr(portrait, "MAX_UPLOAD_BYTES", 100)

    with pytest.raises(ValueError):
        portrait.set_portrait(hero, picture((300, 300)))


def test_removing_the_portrait_deletes_the_file(hero, media):
    portrait.set_portrait(hero, picture())
    name = hero.portrait.name

    portrait.clear_portrait(hero)

    hero.refresh_from_db()
    assert not hero.portrait and not (media / name).exists()
    portrait.clear_portrait(hero)  # nothing to remove is fine

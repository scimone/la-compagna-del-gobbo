"""A character's portrait: the picture the owner uploads for the sheet.

Whatever is uploaded is decoded, turned upright, shrunk and saved again as a WebP - never stored
as it came. That keeps the files small, drops metadata (a phone photo's GPS position) and means a
file that merely *claims* to be an image (an SVG with a script, say) can never be served.
"""

from io import BytesIO
from secrets import token_hex

from django.core.files.base import ContentFile
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.characters.models import Character, CharacterPicture

#: Largest upload accepted, in bytes (a phone photo is a few MB).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: The stored picture fits in this box. The sheet and the overview show it square (1:1, cropped
#: to fit), and large enough that 600 px would look soft.
MAX_SIZE = (1024, 1024)
#: Refuse anything with more pixels than this before decoding it (a decompression bomb).
MAX_PIXELS = 50_000_000
FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


def _encode(upload) -> bytes:
    """The upload as a shrunk, upright WebP. Raises `ValueError` when it is not a usable picture."""
    if getattr(upload, "size", 0) > MAX_UPLOAD_BYTES:
        raise ValueError(_("That picture is too big (10 MB at most)."))
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(_("That picture is too big (10 MB at most)."))
    try:
        picture = Image.open(BytesIO(data))
        if picture.format not in FORMATS:
            raise ValueError(_("Use a JPEG, PNG, WebP or GIF picture."))
        if picture.width * picture.height > MAX_PIXELS:
            raise ValueError(_("That picture is too big."))
        picture = ImageOps.exif_transpose(picture)  # a phone photo's rotation is in its metadata
        picture.thumbnail(MAX_SIZE)
        picture = picture.convert("RGBA" if "A" in picture.getbands() else "RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError(_("That file is not a picture.")) from error
    out = BytesIO()
    picture.save(out, "WEBP", quality=85)
    return out.getvalue()


def set_portrait(character: Character, upload) -> None:
    """Replace the portrait with `upload` (a file-like object). Raises `ValueError` when it is not
    a usable picture; the old one is kept then."""
    data = _encode(upload)
    old = character.portrait.name
    # A new name each time: the browser (and any cache) never shows the previous picture.
    character.portrait.save(f"{character.pk}-{token_hex(4)}.webp", ContentFile(data), save=False)
    character.save(update_fields=["portrait"])
    if old:
        character.portrait.storage.delete(old)


def clear_portrait(character: Character) -> None:
    """Back to the placeholder."""
    if not character.portrait:
        return
    name = character.portrait.name
    character.portrait = ""
    character.save(update_fields=["portrait"])
    character.portrait.storage.delete(name)


#: Pictures a character's gallery can hold.
MAX_GALLERY = 30


def add_picture(character: Character, upload) -> CharacterPicture:
    """Add `upload` to the character's gallery. Raises `ValueError` when it is not a usable
    picture or the gallery is full."""
    if character.pictures.count() >= MAX_GALLERY:
        raise ValueError(_("The gallery is full."))
    data = _encode(upload)
    picture = CharacterPicture(character=character)
    picture.image.save(f"{character.pk}-{token_hex(4)}.webp", ContentFile(data), save=False)
    picture.save()
    return picture


def remove_picture(character: Character, picture_id: int) -> None:
    """Delete one gallery picture (and its file); an unknown id is ignored."""
    picture = character.pictures.filter(pk=picture_id).first()
    if picture is None:
        return
    name = picture.image.name
    storage = picture.image.storage
    picture.delete()
    storage.delete(name)

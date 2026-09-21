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

from apps.characters.models import Character

#: Largest upload accepted, in bytes (a phone photo is a few MB).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: The stored picture fits in this box (portrait-shaped; the sheet only shows it small).
MAX_SIZE = (600, 800)
#: Refuse anything with more pixels than this before decoding it (a decompression bomb).
MAX_PIXELS = 50_000_000
FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


def set_portrait(character: Character, upload) -> None:
    """Replace the portrait with `upload` (a file-like object). Raises `ValueError` when it is not
    a usable picture; the old one is kept then."""
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

    old = character.portrait.name
    # A new name each time: the browser (and any cache) never shows the previous picture.
    character.portrait.save(
        f"{character.pk}-{token_hex(4)}.webp", ContentFile(out.getvalue()), save=False
    )
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

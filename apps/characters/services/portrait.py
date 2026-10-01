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


#: Zoom range of the round avatar's frame, and the avatar's side in pixels.
MAX_ZOOM = 4.0
AVATAR_SIZE = 256


def _frame(cx, cy, zoom) -> tuple[float, float, float]:
    """The three frame numbers, clamped into range. Raises `ValueError` for non-numbers."""
    try:
        cx, cy, zoom = float(cx), float(cy), float(zoom)
    except (TypeError, ValueError) as error:
        raise ValueError(_("Invalid frame.")) from error
    if not all(x == x and abs(x) != float("inf") for x in (cx, cy, zoom)):  # NaN / infinity
        raise ValueError(_("Invalid frame."))
    return (min(max(cx, 0.0), 1.0), min(max(cy, 0.0), 1.0), min(max(zoom, 1.0), MAX_ZOOM))


def set_frame(character: Character, cx, cy, zoom) -> None:
    """Change which part of the portrait the round avatar shows."""
    character.portrait_cx, character.portrait_cy, character.portrait_zoom = _frame(cx, cy, zoom)
    character.save(update_fields=["portrait_cx", "portrait_cy", "portrait_zoom"])


def avatar_bytes(character: Character) -> bytes:
    """The portrait cut to the character's frame, as a small square WebP (shown round by CSS)."""
    with character.portrait.open("rb") as file:
        picture = Image.open(BytesIO(file.read()))
        picture.load()
    width, height = picture.size
    side = min(width, height) / character.portrait_zoom
    left = min(max(character.portrait_cx * width - side / 2, 0), width - side)
    top = min(max(character.portrait_cy * height - side / 2, 0), height - side)
    picture = picture.crop((round(left), round(top), round(left + side), round(top + side)))
    picture = picture.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    out = BytesIO()
    picture.save(out, "WEBP", quality=85)
    return out.getvalue()


def set_portrait(character: Character, upload, frame=(0.5, 0.5, 1.0)) -> None:
    """Replace the portrait with `upload` (a file-like object), framed by `frame` (cx, cy, zoom).
    Raises `ValueError` when it is not a usable picture; the old one is kept then."""
    frame = _frame(*frame)
    data = _encode(upload)
    character.portrait_cx, character.portrait_cy, character.portrait_zoom = frame
    old = character.portrait.name
    # A new name each time: the browser (and any cache) never shows the previous picture.
    character.portrait.save(f"{character.pk}-{token_hex(4)}.webp", ContentFile(data), save=False)
    character.save(update_fields=["portrait", "portrait_cx", "portrait_cy", "portrait_zoom"])
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

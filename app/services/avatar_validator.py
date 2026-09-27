import io

from fastapi import UploadFile

# PIL es la libreria de python para trabajar con imagenes
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import InvalidAvatarError

MAX_AVATAR_SIZE = 5 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

# Valida el archivo de avatar y los requerimientos de su formato (tamaño, extension, etc)
async def validate_avatar(file: UploadFile | None) -> bytes:

    if file is None or not file.filename:
        raise InvalidAvatarError("No image was sent")

    contents = await file.read()

    if not contents:
        raise InvalidAvatarError("The file is empty")

    if len(contents) > MAX_AVATAR_SIZE:
        raise InvalidAvatarError("The image is bigger than 5MB")

    try:
        probe = Image.open(io.BytesIO(contents))
        probe.verify()
    except UnidentifiedImageError:
        raise InvalidAvatarError("The file is not a valid image") from None
    except Exception:
        raise InvalidAvatarError("The file is not a valid image") from None

    # verify() deja la imagen inutilizable para seguir leyendola, hay que reabrirla
    image = Image.open(io.BytesIO(contents))
    if image.format not in ALLOWED_FORMATS:
        raise InvalidAvatarError("Format not allowed. Use JPEG, PNG or WebP")

    return contents

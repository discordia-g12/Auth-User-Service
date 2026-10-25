import io

from fastapi import UploadFile

# PIL es la libreria de python para trabajar con imagenes
from PIL import Image, ImageOps

from app.exceptions import InvalidAvatarError

MAX_AVATAR_SIZE = 5 * 1024 * 1024
MAX_PIXELS = 4096 * 4096  # un PNG chico puede descomprimir a miles de megapíxeles
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
OUTPUT_SIZE = 256


# Valida el archivo de avatar (tamaño, formato real, dimensiones) y lo devuelve como WebP cuadrado de 256 px.
# Recodificar además descarta los metadatos (EXIF con ubicación) y cualquier cosa escondida en el archivo.
async def validate_avatar(file: UploadFile | None) -> bytes:

    if file is None or not file.filename:
        raise InvalidAvatarError("No image was sent")

    contents = await file.read()

    if not contents:
        raise InvalidAvatarError("The file is empty")

    if len(contents) > MAX_AVATAR_SIZE:
        raise InvalidAvatarError("The image is bigger than 5MB")

    try:
        with Image.open(io.BytesIO(contents)) as probe:
            image_format = probe.format
            width, height = probe.size
            probe.verify()
    except Exception:
        raise InvalidAvatarError("The file is not a valid image") from None

    if image_format not in ALLOWED_FORMATS:
        raise InvalidAvatarError("Format not allowed. Use JPEG, PNG or WebP")

    if width * height > MAX_PIXELS:
        raise InvalidAvatarError("The image is bigger than 4096x4096 pixels")

    try:
        # verify() deja la imagen inutilizable para seguir leyendola, hay que reabrirla
        with Image.open(io.BytesIO(contents)) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
            image = ImageOps.fit(image, (OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            image.save(output, format="WEBP", quality=85)
    except Exception:
        raise InvalidAvatarError("The image could not be processed") from None

    return output.getvalue()

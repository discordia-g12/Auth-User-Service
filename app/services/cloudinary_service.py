import cloudinary
import cloudinary.uploader

from app.core.config import settings
from app.core.exceptions import AvatarUploadError

_configured = False

def _ensure_configured() -> None:
    global _configured
    if _configured:
        return
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    _configured = True

# Sube el archivo binario a Cloudinary y devuelve la url publica. Cada user pisa la imagen anterior
def upload_avatar(contents, user_id) -> str:

    _ensure_configured()
    try:
        result = cloudinary.uploader.upload(
            contents,
            folder="avatars",
            public_id=user_id,
            overwrite=True,
            invalidate=True,
            allowed_formats=["jpg", "jpeg", "png", "webp"],
        )
    except Exception as exc:
        raise AvatarUploadError("No se pudo subir la imagen a Cloudinary") from exc

    return result["secure_url"]

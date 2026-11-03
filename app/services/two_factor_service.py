import base64
import hashlib
import io
import secrets
from collections.abc import Callable

import httpx
import pyotp
import qrcode
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger
from app.exceptions import BadRequestError
from app.repositories.two_factor_repository import TwoFactorRepository
from app.schemas.two_factor import (
    TwoFactorActivateResponse,
    TwoFactorDisableResponse,
    TwoFactorRegenerateResponse,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
    TwoFactorVerifyResponse,
)

logger = get_logger(__name__)


def hash_recovery_code(code: str) -> str:
    cleaned = code.strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def generate_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    """Generates formatted plain recovery codes and their SHA-256 hashes."""
    plain_codes: list[str] = []
    hashed_codes: list[str] = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()
        formatted = f"{raw[:4]}-{raw[4:]}"
        plain_codes.append(formatted)
        hashed_codes.append(hash_recovery_code(formatted))
    return plain_codes, hashed_codes


async def default_verify_password(email: str, password: str) -> bool:
    """Verifies user password against Auth0 database connection."""
    if not settings.auth0_domain or not settings.auth0_client_id:
        return True

    url = f"https://{settings.auth0_domain}/oauth/token"
    payload = {
        "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
        "client_id": settings.auth0_client_id,
        "username": email,
        "password": password,
        "realm": settings.auth0_db_connection,
        "scope": "openid",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.auth0_timeout_seconds) as client:
            res = await client.post(url, json=payload)
            return res.status_code == 200
    except httpx.HTTPError as exc:
        logger.error("auth0_password_verification_error", error=str(exc))
        return False


class TwoFactorService:
    """Handles business logic for Two-Factor Authentication (2FA) lifecycle and verification."""

    def __init__(
        self,
        repo: TwoFactorRepository | None = None,
        verify_password_fn: Callable[[str, str], bool] | None = None,
    ):
        self._repo = repo or TwoFactorRepository()
        self._verify_password_fn = verify_password_fn or default_verify_password

    async def get_status(self, session: AsyncSession, user_id: str) -> TwoFactorStatusResponse:
        entity = await self._repo.get_by_user_id(session, user_id)
        if entity is None or not entity.is_enabled:
            return TwoFactorStatusResponse(
                enabled=False,
                has_recovery_codes=False,
                remaining_recovery_codes=0,
            )
        return TwoFactorStatusResponse(
            enabled=True,
            has_recovery_codes=len(entity.recovery_codes) > 0,
            remaining_recovery_codes=len(entity.recovery_codes),
        )

    async def setup_two_factor(
        self,
        session: AsyncSession,
        user_id: str,
        email: str,
    ) -> TwoFactorSetupResponse:
        # Generate new base32 secret
        secret = pyotp.random_base32()
        await self._repo.create_or_update(session, user_id, temp_secret=secret)

        otpauth_url = pyotp.totp.TOTP(secret).provisioning_uri(
            name=email,
            issuer_name="Discordia",
        )

        # Generate QR code PNG Data URI
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(otpauth_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        qr_code = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"

        return TwoFactorSetupResponse(
            secret=secret,
            otpauth_url=otpauth_url,
            qr_code=qr_code,
        )

    async def activate_two_factor(
        self,
        session: AsyncSession,
        user_id: str,
        code: str,
    ) -> TwoFactorActivateResponse:
        entity = await self._repo.get_by_user_id(session, user_id)
        if not entity or not entity.temp_secret:
            raise BadRequestError("No hay ninguna configuración de 2FA pendiente de confirmación.")

        clean_code = code.strip().replace(" ", "")
        totp = pyotp.TOTP(entity.temp_secret)
        if not totp.verify(clean_code, valid_window=2):
            raise BadRequestError("Código de verificación incorrecto o expirado.")

        plain_codes, hashed_codes = generate_recovery_codes(8)
        await self._repo.create_or_update(
            session,
            user_id,
            is_enabled=True,
            secret=entity.temp_secret,
            temp_secret=None,
            recovery_codes=hashed_codes,
        )

        return TwoFactorActivateResponse(
            success=True,
            recovery_codes=plain_codes,
        )

    async def verify_two_factor(
        self,
        session: AsyncSession,
        user_id: str,
        code: str,
    ) -> TwoFactorVerifyResponse:
        entity = await self._repo.get_by_user_id(session, user_id)
        if not entity or not entity.is_enabled or not entity.secret:
            return TwoFactorVerifyResponse(valid=True, recovery_code_used=False, remaining_codes=0)

        clean_code = code.strip().replace(" ", "")

        # 1. TOTP 6-digit code verification (CA 2, CA 3)
        totp = pyotp.TOTP(entity.secret)
        if totp.verify(clean_code, valid_window=2):
            return TwoFactorVerifyResponse(
                valid=True,
                recovery_code_used=False,
                remaining_codes=len(entity.recovery_codes),
            )

        # 2. Single-use recovery code verification (CA 4)
        hashed_attempt = hash_recovery_code(clean_code)
        if hashed_attempt in entity.recovery_codes:
            remaining_codes = [c for c in entity.recovery_codes if c != hashed_attempt]
            await self._repo.create_or_update(
                session,
                user_id,
                recovery_codes=remaining_codes,
            )
            return TwoFactorVerifyResponse(
                valid=True,
                recovery_code_used=True,
                remaining_codes=len(remaining_codes),
            )

        # 3. Invalid code -> Reject login without granting session (CA 3)
        raise BadRequestError("Código de verificación incorrecto o expirado.")

    async def disable_two_factor(
        self,
        session: AsyncSession,
        user_id: str,
        email: str,
        password: str,
    ) -> TwoFactorDisableResponse:
        entity = await self._repo.get_by_user_id(session, user_id)
        if not entity or not entity.is_enabled:
            return TwoFactorDisableResponse(success=True)

        clean_pwd = password.strip()
        is_valid = False

        # 1. Probar como código de recuperación (A1B2-C3D4 o alfanumérico) para cualquier usuario
        if entity.recovery_codes:
            hashed_attempt = hash_recovery_code(clean_pwd)
            if hashed_attempt in entity.recovery_codes:
                is_valid = True

        # 2. Probar como código TOTP (6 dígitos numéricos)
        if not is_valid and entity.secret:
            clean_totp = clean_pwd.replace(" ", "").replace("-", "")
            if clean_totp.isdigit() and len(clean_totp) == 6:
                totp = pyotp.TOTP(entity.secret)
                if totp.verify(clean_totp, valid_window=2):
                    is_valid = True

        # 3. Probar como contraseña (para usuarios de Auth0 con credenciales)
        if not is_valid and email and not user_id.startswith("google-oauth2|"):
            is_valid = await self._verify_password_fn(email, password)

        if not is_valid:
            if user_id.startswith("google-oauth2|"):
                raise BadRequestError("El código de verificación o de recuperación es incorrecto.")
            raise BadRequestError(
                "La confirmación es incorrecta. Ingresá tu contraseña actual, tu código de 6 dígitos o un código de recuperación."
            )

        await self._repo.create_or_update(
            session,
            user_id,
            is_enabled=False,
            secret=None,
            temp_secret=None,
            recovery_codes=[],
        )
        return TwoFactorDisableResponse(success=True)

    async def regenerate_recovery_codes(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> TwoFactorRegenerateResponse:
        entity = await self._repo.get_by_user_id(session, user_id)
        if not entity or not entity.is_enabled:
            raise BadRequestError("La autenticación en dos factores no está activa.")

        plain_codes, hashed_codes = generate_recovery_codes(8)
        await self._repo.create_or_update(
            session,
            user_id,
            recovery_codes=hashed_codes,
        )
        return TwoFactorRegenerateResponse(recovery_codes=plain_codes)

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_two_factor import UserTwoFactor
from app.services.two_factor_service import hash_recovery_code


@pytest.fixture
async def sample_user(db_session: AsyncSession, auth_headers: dict[str, str]) -> User:
    user = User(
        id=auth_headers["X-User-Id"],
        email=auth_headers["X-User-Email"],
        is_active=True,
        is_suspended=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_2fa_status_disabled_by_default(
    client: AsyncClient,
    sample_user: User,
    auth_headers: dict[str, str],
):
    res = await client.get("/api/v1/users/me/2fa/status", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is False
    assert data["has_recovery_codes"] is False
    assert data["remaining_recovery_codes"] == 0


@pytest.mark.asyncio
async def test_2fa_setup_generates_secret_and_qr(
    client: AsyncClient,
    sample_user: User,
    auth_headers: dict[str, str],
):
    # CA 1: Setup generates base32 secret, otpauth url and QR code
    res = await client.post("/api/v1/users/me/2fa/setup", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "secret" in data
    assert len(data["secret"]) >= 16
    assert data["otpauth_url"].startswith("otpauth://totp/Discordia:")
    assert data["qr_code"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_2fa_activation_success_and_invalid_code(
    client: AsyncClient,
    sample_user: User,
    auth_headers: dict[str, str],
):
    # CA 1: Activación exitosa con código TOTP válido
    setup_res = await client.post("/api/v1/users/me/2fa/setup", headers=auth_headers)
    assert setup_res.status_code == 200
    secret = setup_res.json()["secret"]

    # Código incorrecto debe fallar
    bad_res = await client.post(
        "/api/v1/users/me/2fa/activate",
        json={"code": "000000"},
        headers=auth_headers,
    )
    assert bad_res.status_code == 400
    assert "incorrecto o expirado" in bad_res.json()["detail"].lower()

    # Código TOTP correcto activa 2FA y entrega códigos de recuperación
    valid_code = pyotp.TOTP(secret).now()
    act_res = await client.post(
        "/api/v1/users/me/2fa/activate",
        json={"code": valid_code},
        headers=auth_headers,
    )
    assert act_res.status_code == 200
    act_data = act_res.json()
    assert act_data["success"] is True
    assert len(act_data["recovery_codes"]) == 8

    # Verificar que el status ahora es enabled=True
    status_res = await client.get("/api/v1/users/me/2fa/status", headers=auth_headers)
    assert status_res.status_code == 200
    assert status_res.json()["enabled"] is True
    assert status_res.json()["remaining_recovery_codes"] == 8


@pytest.mark.asyncio
async def test_2fa_login_verify_totp(
    client: AsyncClient,
    sample_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
):
    # CA 2: Login con 2FA activo y código correcto
    # CA 3: Código de 2FA incorrecto o expirado
    secret = pyotp.random_base32()
    two_factor = UserTwoFactor(
        user_id=sample_user.id,
        is_enabled=True,
        secret=secret,
        recovery_codes=[hash_recovery_code("ABCD-1234")],
    )
    db_session.add(two_factor)
    await db_session.commit()

    # CA 3: Código incorrecto
    bad_verify = await client.post(
        "/api/v1/users/me/2fa/verify",
        json={"code": "999999"},
        headers=auth_headers,
    )
    assert bad_verify.status_code == 400
    assert "incorrecto o expirado" in bad_verify.json()["detail"].lower()

    # CA 2: Código TOTP correcto
    good_code = pyotp.TOTP(secret).now()
    good_verify = await client.post(
        "/api/v1/users/me/2fa/verify",
        json={"code": good_code},
        headers=auth_headers,
    )
    assert good_verify.status_code == 200
    assert good_verify.json()["valid"] is True
    assert good_verify.json()["recovery_code_used"] is False


@pytest.mark.asyncio
async def test_2fa_login_verify_recovery_code_single_use(
    client: AsyncClient,
    sample_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
):
    # CA 4: Uso de código de recuperación de un solo uso e invalidación
    raw_recovery_code = "SAFE-9988"
    secret = pyotp.random_base32()
    two_factor = UserTwoFactor(
        user_id=sample_user.id,
        is_enabled=True,
        secret=secret,
        recovery_codes=[hash_recovery_code(raw_recovery_code)],
    )
    db_session.add(two_factor)
    await db_session.commit()

    # Usar código de recuperación
    verify_res = await client.post(
        "/api/v1/users/me/2fa/verify",
        json={"code": raw_recovery_code},
        headers=auth_headers,
    )
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert data["valid"] is True
    assert data["recovery_code_used"] is True
    assert data["remaining_codes"] == 0

    # Intentar reusar el mismo código de recuperación -> Debe fallar (ya fue invalidado)
    reuse_res = await client.post(
        "/api/v1/users/me/2fa/verify",
        json={"code": raw_recovery_code},
        headers=auth_headers,
    )
    assert reuse_res.status_code == 400


@pytest.mark.asyncio
async def test_2fa_disable_flow(
    client: AsyncClient,
    sample_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch,
):
    # CA 5: Desactivación de 2FA confirmando con contraseña
    secret = pyotp.random_base32()
    two_factor = UserTwoFactor(
        user_id=sample_user.id,
        is_enabled=True,
        secret=secret,
        recovery_codes=[hash_recovery_code("CODE-1111")],
    )
    db_session.add(two_factor)
    await db_session.commit()

    from app.api.v1.two_factor import two_factor_service

    # Simular validador de contraseña de Auth0
    async def mock_verify(email: str, password: str) -> bool:
        return password == "CorrectPassword123!"

    monkeypatch.setattr(two_factor_service, "_verify_password_fn", mock_verify)

    # Contraseña incorrecta
    bad_dis = await client.post(
        "/api/v1/users/me/2fa/disable",
        json={"password": "WrongPassword"},
        headers=auth_headers,
    )
    assert bad_dis.status_code == 400
    assert "contraseña" in bad_dis.json()["detail"].lower()

    # Contraseña correcta -> 2FA desactivado
    good_dis = await client.post(
        "/api/v1/users/me/2fa/disable",
        json={"password": "CorrectPassword123!"},
        headers=auth_headers,
    )
    assert good_dis.status_code == 200
    assert good_dis.json()["success"] is True

    # Verificar status
    status_res = await client.get("/api/v1/users/me/2fa/status", headers=auth_headers)
    assert status_res.status_code == 200
    assert status_res.json()["enabled"] is False


@pytest.mark.asyncio
async def test_2fa_disable_google_oauth_user_flow(
    client: AsyncClient,
    db_session: AsyncSession,
):
    google_user_id = "google-oauth2|101677372773846085321"
    headers = {
        "X-User-Id": google_user_id,
        "X-User-Email": "google_user@gmail.com",
        "X-User-Email-Verified": "true",
    }
    google_user = User(
        id=google_user_id,
        email="google_user@gmail.com",
        is_active=True,
        is_suspended=False,
    )
    db_session.add(google_user)
    secret = pyotp.random_base32()
    rec_code = "A1B2-C3D4"
    two_factor = UserTwoFactor(
        user_id=google_user_id,
        is_enabled=True,
        secret=secret,
        recovery_codes=[hash_recovery_code(rec_code)],
    )
    db_session.add(two_factor)
    await db_session.commit()

    # 1. Código incorrecto
    bad_res = await client.post(
        "/api/v1/users/me/2fa/disable",
        json={"password": "000000"},
        headers=headers,
    )
    assert bad_res.status_code == 400
    assert "código" in bad_res.json()["detail"].lower()

    # 2. Desactivar con código de recuperación
    rec_res = await client.post(
        "/api/v1/users/me/2fa/disable",
        json={"password": rec_code},
        headers=headers,
    )
    assert rec_res.status_code == 200
    assert rec_res.json()["success"] is True

    # Verificar que quedó desactivado
    status_res = await client.get("/api/v1/users/me/2fa/status", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["enabled"] is False

    # 3. Reactivar y desactivar con TOTP
    two_factor.is_enabled = True
    two_factor.secret = secret
    await db_session.commit()

    totp_code = pyotp.TOTP(secret).now()
    totp_res = await client.post(
        "/api/v1/users/me/2fa/disable",
        json={"password": totp_code},
        headers=headers,
    )
    assert totp_res.status_code == 200
    assert totp_res.json()["success"] is True


@pytest.mark.asyncio
async def test_2fa_regenerate_recovery_codes(
    client: AsyncClient,
    sample_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
):
    secret = pyotp.random_base32()
    two_factor = UserTwoFactor(
        user_id=sample_user.id,
        is_enabled=True,
        secret=secret,
        recovery_codes=[hash_recovery_code("OLD-CODE-1")],
    )
    db_session.add(two_factor)
    await db_session.commit()

    regen_res = await client.post("/api/v1/users/me/2fa/recovery-codes", headers=auth_headers)
    assert regen_res.status_code == 200
    data = regen_res.json()
    assert len(data["recovery_codes"]) == 8

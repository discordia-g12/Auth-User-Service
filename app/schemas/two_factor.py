from pydantic import BaseModel, Field


class TwoFactorStatusResponse(BaseModel):
    """Current 2FA status for the user."""

    enabled: bool = Field(..., description="Whether two-factor authentication is enabled")
    has_recovery_codes: bool = Field(
        ...,
        description="Whether active recovery codes are configured",
    )
    remaining_recovery_codes: int = Field(
        ...,
        description="Number of single-use recovery codes remaining",
    )


class TwoFactorSetupResponse(BaseModel):
    """Data required to configure an authenticator app (TOTP)."""

    secret: str = Field(..., description="Base32 TOTP secret for manual setup")
    otpauth_url: str = Field(..., description="Full otpauth URI for authenticator apps")
    qr_code: str = Field(..., description="PNG image as Data URI to render QR code directly")


class TwoFactorActivateRequest(BaseModel):
    """Payload to confirm TOTP configuration and activate 2FA."""

    code: str = Field(..., min_length=6, max_length=16, description="6-digit verification code")


class TwoFactorActivateResponse(BaseModel):
    """Response returned upon successful 2FA activation with single-use recovery codes."""

    success: bool = True
    recovery_codes: list[str] = Field(
        ...,
        description="List of 8 single-use recovery codes to be safely stored by the user",
    )


class TwoFactorVerifyRequest(BaseModel):
    """Payload to verify TOTP code or single-use recovery code during login."""

    code: str = Field(..., min_length=4, max_length=32, description="6-digit TOTP code or recovery code")


class TwoFactorVerifyResponse(BaseModel):
    """Result of 2FA verification."""

    valid: bool = True
    recovery_code_used: bool = False
    remaining_codes: int = 0


class TwoFactorDisableRequest(BaseModel):
    """Payload to disable 2FA requiring password confirmation (CA 5)."""

    password: str = Field(..., min_length=1, description="Current user password for confirmation")


class TwoFactorDisableResponse(BaseModel):
    """Response returned upon successful 2FA deactivation."""

    success: bool = True


class TwoFactorRegenerateResponse(BaseModel):
    """New single-use recovery codes generated for the user."""

    recovery_codes: list[str] = Field(..., description="New list of 8 single-use recovery codes")


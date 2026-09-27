from app.exceptions import BadRequestError


def no_null_bytes(value: str | None, field_name: str) -> None:
    """Validates that a string does not contain null bytes (\x00)."""
    if value is not None and "\x00" in value:
        raise BadRequestError(f"Field '{field_name}' cannot contain null characters.")

import pytest

from app.exceptions import BadRequestError
from app.services.validation import no_null_bytes


def test_no_null_bytes_valid():
    no_null_bytes("valid_string", "test_field")
    no_null_bytes(None, "test_field")


def test_no_null_bytes_invalid():
    with pytest.raises(BadRequestError) as exc_info:
        no_null_bytes("invalid\x00string", "test_field")
    assert "Field 'test_field' cannot contain null characters." in str(exc_info.value)

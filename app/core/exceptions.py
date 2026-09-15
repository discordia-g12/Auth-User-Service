from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import AppException

__all__ = [
    "AppException",
    "app_exception_handler",
    "http_exception_handler",
    "problem_response",
    "validation_exception_handler",
]


def problem_response(request: Request, status_code: int, title: str, detail: str, invalid_params: list[dict[str, Any]] | None = None) -> JSONResponse:
    content: dict[str, Any] = {"type": "about:blank", "title": title, "status": status_code, "detail": detail, "instance": request.url.path}
    if invalid_params:
        content["invalid_params"] = invalid_params
    return JSONResponse(status_code=status_code, content=content, media_type="application/problem+json")


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return problem_response(request, exc.status_code, exc.title, exc.detail, exc.invalid_params)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    invalid_params = [{"name": ".".join(str(loc) for loc in err["loc"] if loc != "body") or "payload", "reason": err["msg"]} for err in exc.errors()]
    return problem_response(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "Validation Error", "One or more boundary validation rules failed.", invalid_params)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    title = HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus._value2member_map_ else "HTTP Error"
    return problem_response(request, exc.status_code, title, str(exc.detail))

def register_exception_handlers(app: FastAPI) -> None:
    """Wire exceptions to their RFC 7807 handlers."""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

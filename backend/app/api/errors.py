"""Map domain exceptions to HTTP responses (keeps HTTP out of services)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import DomainError
from app.core.logging import get_logger

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain(_: Request, exc: DomainError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("domain_error", code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Preserve FastAPI's structured 422 detail; the catch-all below would
        # otherwise swallow it into an opaque 500.
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {"error": {"code": "validation_error", "details": exc.errors()}}
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error."}},
        )

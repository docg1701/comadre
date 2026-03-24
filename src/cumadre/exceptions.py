"""Custom exception hierarchy for CUMADRE."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

from cumadre.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("request")


class CumadreError(Exception):
    """Base exception for all CUMADRE errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_type: str,
        hint: str,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.hint = hint


class VoiceNotFoundError(CumadreError):
    """Raised when a requested voice is not available."""

    def __init__(self, voice: str, available: list[str]) -> None:
        super().__init__(
            message=f"Voice '{voice}' not found",
            status_code=404,
            error_type="not_found_error",
            hint=(
                f"Available voices: {available}."
                " Place WAV files (3-10s) in the /voices/ directory."
            ),
        )
        self.voice = voice
        self.available = available


class InvalidRequestError(CumadreError):
    """Raised when request parameters are invalid."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            hint=hint,
        )


class GenerationError(CumadreError):
    """Raised when TTS generation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=500,
            error_type="server_error",
            hint=(
                "Check server logs for the full traceback."
                " The TTS model may need restarting."
            ),
        )


class AuthenticationError(CumadreError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Invalid or missing API key") -> None:
        super().__init__(
            message=message,
            status_code=401,
            error_type="authentication_error",
            hint=(
                "Check the API_KEY environment variable and ensure your"
                " Authorization header uses 'Bearer <key>'."
            ),
        )


class ServiceUnavailableError(CumadreError):
    """Raised when the service is not ready to handle requests."""

    def __init__(
        self, message: str = "Service is warming up", *, retry_seconds: int = 30
    ) -> None:
        super().__init__(
            message=message,
            status_code=503,
            error_type="service_unavailable",
            hint=(
                "The service is still loading models."
                f" Retry in {retry_seconds} seconds."
            ),
        )
        self.retry_seconds = retry_seconds


async def cumadre_error_handler(request: Request, exc: CumadreError) -> JSONResponse:
    """Handle CumadreError subclasses with structured JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "type": exc.error_type,
                "hint": exc.hint,
            }
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with generic 500 response."""
    _logger.error("Unhandled exception during request processing", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "An internal server error occurred",
                "type": "server_error",
                "hint": "Check server logs for the full traceback.",
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register centralized exception handlers on the FastAPI app."""
    app.add_exception_handler(CumadreError, cumadre_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)

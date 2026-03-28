"""Custom exception hierarchy for COMADRE."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

from comadre.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("request")


class ComadreError(Exception):
    """Base exception for all COMADRE errors."""

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


class VoiceNotFoundError(ComadreError):
    """Raised when a requested voice is not available."""

    def __init__(self, voice: str, available: list[str]) -> None:
        super().__init__(
            message=f"Voice '{voice}' not found",
            status_code=404,
            error_type="not_found_error",
            hint=(
                f"Available voices: {available}."
                " Use 'kokoro/<name>' for Kokoro voices (.npy files or built-ins)"
                " or 'qwen/<name>' for Qwen3 voices (.wav files in /voices/)."
            ),
        )
        self.voice = voice
        self.available = available


class InvalidRequestError(ComadreError):
    """Raised when request parameters are invalid."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            hint=hint,
        )


class GenerationError(ComadreError):
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


class AuthenticationError(ComadreError):
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


class ServiceUnavailableError(ComadreError):
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


async def comadre_error_handler(request: Request, exc: ComadreError) -> JSONResponse:
    """Handle ComadreError subclasses with structured JSON response."""
    headers: dict[str, str] | None = None
    if isinstance(exc, ServiceUnavailableError):
        headers = {"Retry-After": str(exc.retry_seconds)}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "type": exc.error_type,
                "hint": exc.hint,
            }
        },
        headers=headers,
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
    app.add_exception_handler(ComadreError, comadre_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)

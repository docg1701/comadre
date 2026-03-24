"""Custom exception hierarchy for CUMADRE."""


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

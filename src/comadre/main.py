"""Comadre FastAPI application entry point."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from comadre import __version__
from comadre.api import api_router
from comadre.config import get_settings
from comadre.download import ensure_kokoro_models, ensure_qwen3_models
from comadre.exceptions import RateLimitError, register_exception_handlers
from comadre.health import build_health_response
from comadre.logging import get_logger, setup_logging
from comadre.rate_limit import get_client_ip, limiter
from comadre.service import EngineRouter, KokoroEngine, QwenEngine

logger = get_logger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup sequence."""
    settings = get_settings()

    # Initialize state early (health endpoint needs these during startup)
    app.state.ready = False
    app.state.queue_lock = asyncio.Lock()
    app.state.queue_depth = 0
    app.state.start_time = time.monotonic()
    app.state.settings = settings
    app.state.router = None

    # Phase 1: Load config (already done via get_settings)
    logger.info("Configuration loaded")

    # Phase 2: Configure structured logging
    setup_logging()
    logger.info("Structured logging configured")

    # Phase 2.5: Ensure models are downloaded (non-blocking)
    logger.info("Checking model files...")
    await asyncio.to_thread(
        ensure_kokoro_models,
        model_path=settings.kokoro_model_path,
        voices_path=settings.kokoro_voices_path,
        model_url=settings.kokoro_model_url,
        voices_url=settings.kokoro_voices_url,
    )
    if settings.qwen3_enabled:
        await asyncio.to_thread(
            ensure_qwen3_models,
            model_path=settings.qwen3_model_path,
            tokenizer_path=settings.qwen3_tokenizer_path,
            model_url=settings.qwen3_model_url,
            tokenizer_url=settings.qwen3_tokenizer_url,
        )
    else:
        logger.info("Qwen3 disabled (QWEN3_ENABLED=false), skipping model check")
    logger.info("Model check complete")

    # Phase 2.7: Verify noise directory
    noise_path = Path(settings.noise_dir)
    if not noise_path.is_dir():
        logger.warning("Noise directory not found: %s", settings.noise_dir)
    else:
        logger.info("Noise directory found: %s", settings.noise_dir)

    # Phase 3: Verify espeak-ng pt_extra data
    logger.info("Verifying espeak-ng pt_extra dictionary...")
    if settings.espeak_data_path:
        pt_extra = Path(settings.espeak_data_path)
        if pt_extra.is_dir():
            logger.info("espeak-ng pt_extra found: %s", settings.espeak_data_path)
        else:
            logger.warning(
                "espeak-ng pt_extra path not found: %s", settings.espeak_data_path
            )
    else:
        logger.info("No custom espeak-ng data path configured")

    # Phase 4: Verify voices directory
    voices_dir = Path(settings.voices_dir)
    kokoro_voices_dir = voices_dir / "kokoro"
    qwen_voices_dir = voices_dir / "qwen"
    if voices_dir.is_dir():
        logger.info("Voices directory found: %s", settings.voices_dir)
        if not kokoro_voices_dir.is_dir():
            logger.warning(
                "Kokoro voices subdirectory not found: %s", kokoro_voices_dir
            )
        if not qwen_voices_dir.is_dir():
            logger.warning("Qwen3 voices subdirectory not found: %s", qwen_voices_dir)
    else:
        logger.warning("Voices directory not found: %s", settings.voices_dir)

    try:
        # Phase 5: Load Kokoro model
        logger.info("Loading Kokoro TTS model...")
        kokoro = KokoroEngine()
        kokoro.load_model(
            model_path=settings.kokoro_model_path,
            voices_path=settings.kokoro_voices_path,
            espeak_data_path=settings.espeak_data_path,
        )

        # Phase 6: Verify Qwen3 binary (skip when disabled)
        qwen = QwenEngine()
        if settings.qwen3_enabled:
            logger.info("Verifying qwen3-tts-cli binary...")
            qwen.load_model(
                cli_path=settings.qwen3_cli_path,
                model_path=settings.qwen3_model_path,
                tokenizer_path=settings.qwen3_tokenizer_path,
                threads=settings.qwen3_threads,
            )
        else:
            logger.info("Qwen3 disabled, skipping engine load")

        # Phase 7: Warm up Kokoro
        logger.info("Warming up Kokoro engine...")
        kokoro.warm_up()

        # Phase 8: Warm up Qwen3 (using first available reference WAV)
        if settings.qwen3_enabled:
            logger.info("Warming up Qwen3 engine...")
            qwen_warmup_ref: Path | None = None
            if qwen_voices_dir.is_dir():
                wavs = sorted(qwen_voices_dir.glob("*.wav"))
                if wavs:
                    qwen_warmup_ref = wavs[0]
            qwen.warm_up(reference_path=qwen_warmup_ref)
    except Exception:
        logger.critical("Startup failed during engine initialization", exc_info=True)
        raise

    # Phase 9: Ready
    router = EngineRouter(kokoro=kokoro, qwen=qwen, voices_dir=voices_dir)
    app.state.router = router
    app.state.ready = True

    # Validate default voice is resolvable
    default = settings.default_voice
    if default not in router.available_voices():
        try:
            router._parse_voice(default)
        except Exception:
            logger.warning(
                "DEFAULT_VOICE '%s' has invalid format — requests"
                " without explicit voice will fail",
                default,
            )

    logger.info("Service ready on http://0.0.0.0:%d", settings.port)

    yield

    # Shutdown
    logger.info("Shutting down...")


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Convert FastAPI 422 validation errors to 400 with consistent error format."""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "message": "Invalid request body",
                "type": "invalid_request_error",
                "hint": (
                    'Expected JSON: {"input": "text to speak",'
                    ' "voice": "kokoro/pm_santa", "response_format": "ogg"}'
                ),
            }
        },
    )


def _rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert slowapi RateLimitExceeded to our error format."""
    error = RateLimitError(retry_after=60)
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "message": error.message,
                "type": error.error_type,
                "hint": error.hint,
            }
        },
        headers={"Retry-After": "60"},
    )


def _method_not_allowed_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert Starlette HTTPException(405) to our standard error format.

    Without this handler, FastAPI returns ``{"detail": "Method Not Allowed"}``
    which breaks the consistent ``{"error": {message, type, hint}}`` envelope
    used everywhere else. The Allow header from the original exception is
    preserved when present.
    """
    headers: dict[str, str] | None = None
    exc_headers = getattr(exc, "headers", None)
    if isinstance(exc_headers, dict) and "Allow" in exc_headers:
        headers = {"Allow": exc_headers["Allow"]}
    return JSONResponse(
        status_code=405,
        content={
            "error": {
                "message": f"Method {request.method} not allowed on {request.url.path}",
                "type": "method_not_allowed_error",
                "hint": (
                    "Use POST for /v1/audio/speech and GET for /health."
                    " See docs/api-reference.md for the full method list."
                ),
            }
        },
        headers=headers,
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Comadre",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    access_logger = get_logger("access")

    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next: Any) -> Response:
        start = time.monotonic()
        response: Response = await call_next(request)
        duration = time.monotonic() - start
        client_ip = get_client_ip(request)
        access_logger.info(
            "%s %s %s %d %.1fs",
            client_ip,
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response

    register_exception_handlers(app)
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(405, _method_not_allowed_handler)
    app.add_exception_handler(429, _rate_limit_exceeded_handler)
    app.include_router(api_router)

    @app.get("/health")
    @limiter.limit(settings.rate_limit_health)
    async def health_endpoint(request: Request) -> JSONResponse:
        if not getattr(request.app.state, "ready", False):
            router = getattr(request.app.state, "router", None)
            if router is None:
                return JSONResponse(
                    content={
                        "status": "warming_up",
                        "voices": [],
                        "engines": {},
                        "queue_depth": 0,
                        "uptime_seconds": 0,
                        "memory_mb": 0,
                        "version": __version__,
                    },
                    status_code=503,
                )
        body, status_code = build_health_response(
            router=request.app.state.router,
            ready=request.app.state.ready,
            start_time=request.app.state.start_time,
            queue_depth=request.app.state.queue_depth,
        )
        return JSONResponse(content=body, status_code=status_code)

    return app

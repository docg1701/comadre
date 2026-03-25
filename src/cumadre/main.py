"""CUMADRE FastAPI application entry point."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cumadre import __version__
from cumadre.api import api_router
from cumadre.config import get_settings
from cumadre.download import ensure_kokoro_models, ensure_qwen3_models
from cumadre.exceptions import register_exception_handlers
from cumadre.health import build_health_response
from cumadre.logging import get_logger, setup_logging
from cumadre.service import EngineRouter, KokoroEngine, QwenEngine

logger = get_logger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: 9-phase startup sequence."""
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
    await asyncio.to_thread(
        ensure_qwen3_models,
        model_path=settings.qwen3_model_path,
        tokenizer_path=settings.qwen3_tokenizer_path,
        model_url=settings.qwen3_model_url,
        tokenizer_url=settings.qwen3_tokenizer_url,
    )
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

    # Phase 4: Detect clone reference WAV
    logger.info("Detecting clone reference WAV...")
    if settings.clone_reference_path:
        if Path(settings.clone_reference_path).is_file():
            logger.info("Clone reference found: %s", settings.clone_reference_path)
        else:
            logger.warning(
                "Clone reference not found: %s", settings.clone_reference_path
            )
    else:
        logger.info("No clone reference configured — clone voice disabled")

    try:
        # Phase 5: Load Kokoro model
        logger.info("Loading Kokoro TTS model...")
        kokoro = KokoroEngine()
        kokoro.load_model(
            model_path=settings.kokoro_model_path,
            voices_path=settings.kokoro_voices_path,
            espeak_data_path=settings.espeak_data_path,
        )

        # Phase 6: Verify Qwen3 binary
        logger.info("Verifying qwen3-tts-cli binary...")
        qwen = QwenEngine()
        qwen.load_model(
            cli_path=settings.qwen3_cli_path,
            model_path=settings.qwen3_model_path,
            tokenizer_path=settings.qwen3_tokenizer_path,
            female_reference_path=settings.qwen3_female_reference_path,
            male_reference_path=settings.qwen3_male_reference_path,
            clone_reference_path=settings.clone_reference_path,
            threads=settings.qwen3_threads,
        )

        # Phase 7: Warm up Kokoro
        logger.info("Warming up Kokoro engine...")
        kokoro.warm_up()

        # Phase 8: Warm up Qwen3
        logger.info("Warming up Qwen3 engine...")
        qwen.warm_up()
    except Exception:
        logger.critical("Startup failed during engine initialization", exc_info=True)
        raise

    # Phase 9: Ready
    router = EngineRouter(kokoro=kokoro, qwen=qwen)
    app.state.router = router
    app.state.ready = True

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
                    ' "voice": "santa", "response_format": "ogg"}'
                ),
            }
        },
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CUMADRE",
        version=__version__,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.include_router(api_router)

    @app.get("/health")
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
                        "clone_configured": False,
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

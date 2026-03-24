"""Tests for asyncio.Lock queue behavior in speech endpoint."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

from cumadre.exceptions import GenerationError


class TestSequentialProcessing:
    """Two concurrent requests are processed one at a time under asyncio.Lock."""

    async def test_concurrent_requests_processed_sequentially(
        self,
        app: Any,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        timestamps: list[tuple[str, float]] = []

        def slow_generate(*args: object, **kwargs: object) -> bytes:
            timestamps.append(("start", time.monotonic()))
            # Sleep to hold the lock
            time.sleep(0.1)
            timestamps.append(("end", time.monotonic()))
            return b"fake-audio-bytes"

        mock_router.generate_speech.side_effect = slow_generate

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            r1, r2 = await asyncio.gather(
                client.post(
                    "/v1/audio/speech",
                    json={"input": "First", "voice": "santa"},
                    headers=auth_headers,
                ),
                client.post(
                    "/v1/audio/speech",
                    json={"input": "Second", "voice": "santa"},
                    headers=auth_headers,
                ),
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        # Both calls completed
        assert len(timestamps) == 4
        # Verify label ordering (prevents false pass if lock is removed)
        assert timestamps[0][0] == "start"
        assert timestamps[1][0] == "end"
        assert timestamps[2][0] == "start"
        assert timestamps[3][0] == "end"
        # Second start must be after first end (sequential, not parallel)
        first_end = timestamps[1][1]
        second_start = timestamps[2][1]
        assert second_start >= first_end


class TestQueueDepth:
    """Queue depth increments and decrements correctly."""

    async def test_queue_depth_during_processing(
        self,
        app: Any,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        depth_during: list[int] = []

        def capture_depth(*args: object, **kwargs: object) -> bytes:
            depth_during.append(app.state.queue_depth)
            return b"fake-audio-bytes"

        mock_router.generate_speech.side_effect = capture_depth

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/audio/speech",
                json={"input": "Hello", "voice": "santa"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        # queue_depth is 1 during processing (incremented before lock)
        assert depth_during == [1]
        # queue_depth returns to 0 after completion
        assert app.state.queue_depth == 0

    async def test_queue_depth_decrements_on_error(
        self,
        app: Any,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        mock_router.generate_speech.side_effect = GenerationError("Simulated failure")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/audio/speech",
                json={"input": "Hello", "voice": "santa"},
                headers=auth_headers,
            )

        assert response.status_code == 500
        # queue_depth returns to 0 even after error (finally block)
        assert app.state.queue_depth == 0

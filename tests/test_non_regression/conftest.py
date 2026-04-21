"""Shared fixtures for the CI non-regression suite.

The suite boots the production Caddy image with the production ``Caddyfile``
against a stubbed upstream so assertions exercise the real reverse-proxy
header surface without paying the Kokoro/Qwen3 model-download cost.

Strategy A (caddy-only + nginx stub on a user-defined Docker network) is the
current implementation. See ``tests/test_non_regression/README.md`` for the
rationale and the extension contract for stories 4.5b-4.5g.
"""

from __future__ import annotations

import shutil
import ssl
import subprocess
import time
import warnings
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

warnings.filterwarnings("ignore", message=".*[Uu]nverified HTTPS.*")

_LABEL = "comadre-non-regression"
_NETWORK = "comadre-non-regression-net"
_CADDY_CONTAINER = "comadre-nr-caddy"
_UPSTREAM_CONTAINER = "comadre-nr-upstream"
_UPSTREAM_HOSTNAME = "tts-service"
_BASE_URL = "https://localhost"

_UPSTREAM_NGINX_CONF = """\
events {}
http {
    access_log /dev/null;
    server {
        listen 8000 default_server;
        location / {
            add_header Content-Type text/plain;
            return 200 "non-regression-stub\\n";
        }
    }
}
"""


def _docker(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``docker`` with stderr surfaced via ``pytest.fail`` on non-zero exit.

    The default ``CalledProcessError.__str__`` shows only the exit code, which
    turns a CI failure into an opaque ``returncode 125`` — operators then have
    to re-run locally to see what docker actually rejected. Wrapping here
    makes the fixture-side failure message carry the captured stderr.
    """
    try:
        return subprocess.run(
            ["docker", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() or "(no output)"
        pytest.fail(f"docker {' '.join(args)} failed (exit {exc.returncode}): {detail}")


def _prepull_images() -> None:
    """Pull the two images the session fixture needs before the readiness poll.

    Docker-Hub throttling on cold CI runners can push the first ``docker run``
    past the 30 s wait budget. Pre-pulling separates the "image fetch" wall
    time from the "stack comes up" wall time so a slow pull surfaces as a
    pull error, not as a confusing "Caddy did not come up" timeout.
    """
    for image in ("caddy:2-alpine", "nginx:alpine"):
        subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            check=False,
        )


def _tear_down_stack() -> None:
    probe = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    ids = [line for line in probe.stdout.split() if line]
    if ids:
        subprocess.run(
            ["docker", "rm", "-f", *ids],
            capture_output=True,
            check=False,
        )
    subprocess.run(
        ["docker", "network", "rm", _NETWORK],
        capture_output=True,
        check=False,
    )


_READY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.RequestError,
    ssl.SSLError,
    OSError,
)


def _wait_for_caddy(timeout_seconds: float = 30.0) -> None:
    """Poll HTTP (port 80) AND HTTPS (port 443) until both return non-5xx.

    The earlier implementation returned on the first successful HTTPS
    response regardless of status, which could fire before Caddy's
    self-signed cert was provisioned or before port 80 was bound — both
    latent flakes for the 308 probe and the parametrised matrix. The
    tightened readiness signal is "Caddy has answered both ports with a
    non-5xx status at least once". Exceptions are narrowed to the
    connect/TLS/read family so a real bug does not get swallowed by the
    original ``except Exception`` blanket.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error: BaseException | str | None = None
    while time.monotonic() < deadline:
        try:
            https_resp = httpx.get(
                f"{_BASE_URL}/",
                verify=False,
                follow_redirects=False,
                timeout=2.0,
            )
            http_resp = httpx.get(
                "http://localhost/",
                follow_redirects=False,
                timeout=2.0,
            )
            if https_resp.status_code < 500 and http_resp.status_code < 500:
                return
            last_error = (
                f"HTTPS {https_resp.status_code} / HTTP {http_resp.status_code}"
            )
        except _READY_EXCEPTIONS as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(
        f"Caddy non-regression stack did not come up within "
        f"{timeout_seconds}s: {last_error!r}"
    )


@pytest.fixture(scope="session")
def compose_stack(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[str]:
    """Yield the HTTPS base URL of a locally-spawned Caddy + nginx stub stack.

    Skips the whole module when docker is unavailable so a developer running
    ``uv run pytest -m non_regression`` without docker gets a clear reason
    rather than a stack of subprocess errors.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not on PATH")
    # Skip (not fail) when the daemon is down so a laptop developer running
    # ``pytest -m non_regression`` without docker gets a clean skip reason.
    # ``_docker`` below converts CalledProcessError into pytest.fail, which is
    # the desired shape once we are past this gate — so the daemon check uses
    # subprocess directly.
    probe = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(
            f"docker daemon unavailable: {(probe.stderr or probe.stdout).strip()}"
        )

    _prepull_images()

    repo_root = Path(__file__).resolve().parents[2]
    caddyfile = repo_root / "deploy" / "caddy" / "Caddyfile"
    landing_dir = repo_root / "deploy" / "landing"
    if not caddyfile.is_file():
        pytest.fail(f"Caddyfile missing at {caddyfile}")
    if not landing_dir.is_dir():
        pytest.fail(f"Landing dir missing at {landing_dir}")

    tmp_dir = tmp_path_factory.mktemp("non-regression")
    nginx_conf = tmp_dir / "nginx.conf"
    nginx_conf.write_text(_UPSTREAM_NGINX_CONF)

    _tear_down_stack()

    try:
        _docker(["network", "create", "--label", f"{_LABEL}=true", _NETWORK])
        _docker(
            [
                "run",
                "-d",
                "--name",
                _UPSTREAM_CONTAINER,
                "--hostname",
                _UPSTREAM_HOSTNAME,
                "--network",
                _NETWORK,
                "--network-alias",
                _UPSTREAM_HOSTNAME,
                "--label",
                _LABEL,
                "-v",
                f"{nginx_conf}:/etc/nginx/nginx.conf:ro",
                "nginx:alpine",
            ]
        )
        _docker(
            [
                "run",
                "-d",
                "--name",
                _CADDY_CONTAINER,
                "--network",
                _NETWORK,
                "--label",
                _LABEL,
                "-p",
                "127.0.0.1:80:80",
                "-p",
                "127.0.0.1:443:443",
                "-v",
                f"{caddyfile}:/etc/caddy/Caddyfile:ro",
                "-v",
                f"{landing_dir}:/srv/www:ro",
                "-e",
                "DOMAIN=localhost",
                "caddy:2-alpine",
            ]
        )
        _wait_for_caddy()
        yield _BASE_URL
    finally:
        _tear_down_stack()


@pytest.fixture()
def probe_client(compose_stack: str) -> Iterator[httpx.Client]:
    """HTTPS client targeting the locally-spawned Caddy stack.

    ``verify=False`` because Caddy's localhost cert is self-signed.
    ``follow_redirects=False`` because the HTTP->HTTPS 308 is a first-class
    probe target (AC6), not a transparent implementation detail to hide.
    """
    with httpx.Client(
        base_url=compose_stack,
        verify=False,
        follow_redirects=False,
        timeout=5.0,
    ) as client:
        yield client

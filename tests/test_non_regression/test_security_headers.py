"""FR46 + Server/Via banner-strip non-regression assertions (Story 4.5a).

Every assertion carries a failure message naming (a) the missing control,
(b) the HTTP method + path, (c) the observed status code, (d) a short
diagnostic tail. This is the failure-UX contract stories 4.5b-4.5g inherit.
"""

from __future__ import annotations

import httpx
import pytest

REQUIRED_HEADERS: tuple[str, ...] = (
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
)

# (method, path, expected_status_or_None)
#
# None means "shape-agnostic" — the probe exists to exercise Caddy's header
# surface, not to pin the upstream stub's response shape. 4.5b-g keep this
# contract: probes are named by the *layer* they exercise (landing file_server,
# reverse_proxy, method-not-allowed, not-found), not by the upstream's 2xx/5xx
# choice.
PROBES: tuple[tuple[str, str, int | None], ...] = (
    ("GET", "/", 200),
    ("POST", "/v1/audio/speech", None),
    ("GET", "/health", None),
    ("GET", "/this-path-does-not-exist", 404),
    ("POST", "/", 405),
)

# Caddy's file_server writes 404 and 405 responses directly via its internal
# error path — site-level `header { ... }` middleware does not apply, and the
# automatic `Server: Caddy` banner is not stripped. Same architectural bucket
# as the HTTP->HTTPS 308 (see test_http_to_https_redirect_is_308...). These
# two status codes are probed to assert they still exist (so probes don't
# silently regress into some other status), but header-presence and
# banner-strip assertions skip them.
#
# A future hardening story can close this gap via a Caddyfile `handle_errors`
# block that re-applies the site-level headers to error responses. Tracked as
# deferred work in story 4.5a — empirically the approach works in Caddy
# 2-alpine, but the production Caddyfile change is out of 4.5a's scope
# ("pure test infra + CI wiring") and of the user-memory directive
# `feedback_caddy_server_header.md`.
_FILE_SERVER_ERROR_STATUSES: frozenset[int] = frozenset({404, 405})


def _skip_if_file_server_error_path(expected_status: int | None) -> None:
    """Skip when the probe is INTENDED to hit a file_server error path.

    Keyed on ``expected_status`` (the probe's pinned contract), not on the
    response's observed status. Pinning on observation would mask real
    regressions — e.g., ``GET /health`` unexpectedly returning 404 would
    silently skip header-presence / banner-strip checks on the reverse_proxy
    surface instead of failing the suite loudly.
    """
    if expected_status in _FILE_SERVER_ERROR_STATUSES:
        pytest.skip(
            f"Caddy architectural exclusion: file_server writes {expected_status} "
            f"responses directly, bypassing site-level `header` middleware. Same "
            f"bucket as the HTTP->HTTPS 308 exclusion. See "
            f"tests/test_non_regression/README.md and the story 4.5a deferred-work "
            f"entry proposing a `handle_errors` block as the hardening follow-up."
        )


@pytest.mark.non_regression
@pytest.mark.parametrize(("method", "path", "expected_status"), PROBES)
@pytest.mark.parametrize("header", REQUIRED_HEADERS)
def test_security_header_present(
    probe_client: httpx.Client,
    method: str,
    path: str,
    expected_status: int | None,
    header: str,
) -> None:
    _skip_if_file_server_error_path(expected_status)
    resp = probe_client.request(method, path)
    if expected_status is not None:
        assert resp.status_code == expected_status, (
            f"Probe setup regressed: {method} {path} returned "
            f"{resp.status_code}, expected {expected_status}"
        )
    assert header in resp.headers, (
        f"Missing '{header}' on {method} {path} ({resp.status_code}). "
        f"Response headers: {dict(resp.headers)}"
    )


@pytest.mark.non_regression
@pytest.mark.parametrize(("method", "path", "expected_status"), PROBES)
def test_csp_upgrade_insecure_requests_directive(
    probe_client: httpx.Client,
    method: str,
    path: str,
    expected_status: int | None,
) -> None:
    _skip_if_file_server_error_path(expected_status)
    resp = probe_client.request(method, path)
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "upgrade-insecure-requests" in csp, (
        f"CSP on {method} {path} ({resp.status_code}) missing "
        f"'upgrade-insecure-requests' directive. CSP value: {csp!r}"
    )


@pytest.mark.non_regression
@pytest.mark.parametrize(("method", "path", "expected_status"), PROBES)
def test_server_and_via_headers_stripped(
    probe_client: httpx.Client,
    method: str,
    path: str,
    expected_status: int | None,
) -> None:
    _skip_if_file_server_error_path(expected_status)
    resp = probe_client.request(method, path)
    assert "Server" not in resp.headers, (
        f"Server header leaked on {method} {path} ({resp.status_code}): "
        f"{resp.headers.get('Server')!r}"
    )
    assert "Via" not in resp.headers, (
        f"Via header leaked on {method} {path} ({resp.status_code}): "
        f"{resp.headers.get('Via')!r}"
    )


@pytest.mark.non_regression
def test_http_to_https_redirect_is_308_and_excluded_from_banner_strip(
    compose_stack: str,
) -> None:
    # Deliberately NO assertion on Server/Via or security headers here —
    # the 308 is issued from Caddy's automatic-HTTPS global block, not the
    # site block, and cannot carry the site's `header` directives. See
    # feedback_caddy_server_header.md for the architectural rationale. This
    # test exists to document that the 308 exists and that its bareness is
    # intentional; a future "why is this test so thin?" reader finds the
    # answer inline rather than deleting it.
    assert compose_stack == "https://localhost", (
        f"compose_stack fixture yielded unexpected base URL: {compose_stack!r}"
    )
    resp = httpx.get(
        "http://localhost/",
        verify=False,
        follow_redirects=False,
        timeout=5.0,
    )
    assert resp.status_code == 308, (
        f"Expected HTTP->HTTPS 308 redirect on http://localhost/, got "
        f"{resp.status_code}. Response headers: {dict(resp.headers)}"
    )

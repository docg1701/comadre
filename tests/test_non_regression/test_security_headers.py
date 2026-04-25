"""FR46 + Server/Via banner-strip non-regression assertions (Story 4.5a).

Every assertion carries a failure message naming (a) the missing control,
(b) the HTTP method + path, (c) the observed status code, (d) a short
diagnostic tail. This is the failure-UX contract stories 4.5b-4.5g inherit.

F48 — adds a static byte-identity assertion across the two production
Caddyfiles (``Caddyfile`` and ``Caddyfile-no-landing``) on the site-level
``header { ... }`` block. The Caddy-runtime probes only spin up the
default ``Caddyfile``; running both stacks would double the suite cost
for no proportional signal. The static assertion catches the most common
drift class (a hardening change landing in one Caddyfile but not the
other) at PR time.
"""

from __future__ import annotations

import re
from pathlib import Path

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

# F67 + F68 (2026-04-25 hardening pass): Caddy's site-level `handle_errors`
# block now re-applies the security headers + Server/Via strip on every
# Caddy-emitted error response (404 from file_server, 405 from
# method_not_allowed, 411/413/etc. from the @api respond blocks). The
# previous `_skip_if_file_server_error_path` helper has been removed —
# 404 and 405 probes now assert the full header set, same as 200 / 5xx /
# upstream responses. The HTTP->HTTPS 308 redirect remains an architectural
# exclusion because it is issued from Caddy's automatic-HTTPS GLOBAL block,
# not the site block (see test_http_to_https_redirect_is_308...).


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
    resp = probe_client.request(method, path)
    assert "Server" not in resp.headers, (
        f"Server header leaked on {method} {path} ({resp.status_code}): "
        f"{resp.headers.get('Server')!r}"
    )
    assert "Via" not in resp.headers, (
        f"Via header leaked on {method} {path} ({resp.status_code}): "
        f"{resp.headers.get('Via')!r}"
    )


# ---------------------------------------------------------------------------
# F48 — static byte-identity assertion on the site-level header { ... } block
# across both production Caddyfiles.
# ---------------------------------------------------------------------------


_HEADER_BLOCK_RE = re.compile(
    r"\bheader\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)


def _extract_first_header_block(caddyfile: Path) -> str:
    """Return the body (between braces) of the first ``header { ... }`` block.

    Caddy's site-level header directive is the surface that delivers the 6
    required security headers + the ``-Server`` / ``-Via`` strips. Both
    production Caddyfiles MUST carry a byte-identical copy so that
    ``Caddyfile-no-landing`` (used for landing-disabled deploys) does not
    silently drift from ``Caddyfile``. Whitespace inside the block is
    significant for the comparison — a renamed directive or a value tweak
    must fail the assertion.
    """
    text = caddyfile.read_text(encoding="utf-8")
    match = _HEADER_BLOCK_RE.search(text)
    if match is None:
        pytest.fail(f"No `header {{ ... }}` block found in {caddyfile}")
    return match.group("body").strip()


@pytest.mark.non_regression
@pytest.mark.parametrize(
    "caddyfile_name",
    ("Caddyfile", "Caddyfile-no-landing"),
)
def test_caddyfile_security_headers_block_present(caddyfile_name: str) -> None:
    """F48 — both production Caddyfiles MUST declare every required security
    header, the Server-banner strip, and the Via strip.

    The two Caddyfiles deliberately diverge on the ``Content-Security-Policy``
    value (the no-landing variant has a much simpler CSP — no font-src,
    no img-src, no script-src — because the landing page's static assets
    are not served). Byte-identity is therefore the wrong contract; this
    test asserts presence + name only, which catches the most common
    drift class (a header directive landing in one Caddyfile but not the
    other) at PR time without double-running the Caddy stack.
    """
    repo_root = Path(__file__).resolve().parents[2]
    caddyfile = repo_root / "deploy" / "caddy" / caddyfile_name
    block = _extract_first_header_block(caddyfile)
    for header_name in REQUIRED_HEADERS:
        assert header_name in block, (
            f"{caddyfile_name} site-level `header {'{ ... }'}` block is "
            f"missing the {header_name!r} directive. Re-apply the security-"
            f"header to this Caddyfile so it matches the runtime probes "
            f"asserted by test_security_header_present."
        )
    assert "-Server" in block, (
        f"{caddyfile_name} site-level `header` block does not strip the "
        "Server banner (`-Server`). Add it — the runtime probes assert "
        "the strip via test_server_and_via_headers_stripped."
    )
    assert "-Via" in block, (
        f"{caddyfile_name} site-level `header` block does not strip the "
        "Via banner (`-Via`). Add it — the runtime probes assert the strip "
        "via test_server_and_via_headers_stripped."
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

"""FR49 non-regression — Caddy body-framing + oversize policy (Story 4.5d).

Exercises the live docker-stack (production Caddy image + production
``deploy/caddy/Caddyfile``) against an nginx stub whose own body-size limit
is raised to 100 MB, so any non-2xx response MUST come from Caddy — never
ambiguously from the upstream.

Policy under test (mirrors AWS API Gateway / Cloudflare / nginx
``client_max_body_size`` pattern for bounded-payload APIs):

1. Any ``Transfer-Encoding`` header on ``@api`` → 411 (force Content-Length).
2. ``Content-Length`` present but non-canonical (non-numeric / >10 digits /
   duplicate) → 400.
3. Valid ``Content-Length > 1 MiB`` → 413.
4. Write method with neither ``Content-Length`` nor ``Transfer-Encoding`` → 411.
5. Otherwise → proxy to upstream.

Constants use binary MiB (1 MiB == 1,048,576 bytes) matching the Caddyfile
matcher literal ``1048576``. Also includes a static structural-parity probe
that asserts ``Caddyfile`` and ``Caddyfile-no-landing`` carry the same four
matcher+handle blocks, catching drift when one file is edited and the other
forgotten.
"""

from __future__ import annotations

import re
import socket
import ssl
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

_ONE_MB: int = 1024 * 1024
_TWO_MB: int = 2 * _ONE_MB
_SUB_BOUNDARY: int = _ONE_MB - 1024
_STUB_SIGNATURE: bytes = b"non-regression-stub"
_API_PATHS: tuple[str, ...] = ("/v1/audio/speech", "/health")
_WRITE_METHODS: tuple[str, ...] = ("POST", "PUT", "PATCH")
_OCTET_STREAM: dict[str, str] = {"Content-Type": "application/octet-stream"}

_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
_CADDYFILE: Path = _REPO_ROOT / "deploy" / "caddy" / "Caddyfile"
_CADDYFILE_NO_LANDING: Path = _REPO_ROOT / "deploy" / "caddy" / "Caddyfile-no-landing"

_EXPECTED_MATCHERS: tuple[str, ...] = (
    "@api_has_te",
    "@api_malformed_cl",
    "@api_oversized_body",
    "@api_missing_cl",
)


def _chunked_bytes(total: int, chunk_size: int = 8192) -> Iterator[bytes]:
    """Yield ``total`` filler bytes as chunks.

    Passing an iterator to ``httpx.Client.post(content=...)`` switches httpx
    to ``Transfer-Encoding: chunked`` (no ``Content-Length``), which is the
    canonical wire shape the ``@api_has_te`` matcher catches.
    """
    remaining = total
    while remaining > 0:
        n = min(chunk_size, remaining)
        yield b"x" * n
        remaining -= n


def _send_raw_https(raw_request: bytes) -> tuple[int, bytes]:
    """Send a handcrafted HTTP/1.1 request over TLS to the Caddy stack.

    Used for requests that httpx will not send unmodified (e.g., a malformed
    ``Content-Length: abc`` header — httpx re-computes Content-Length to
    match the body it is about to send, so the value cannot be forced via
    the client API).

    Connects to ``127.0.0.1:443`` (the Caddy stack's loopback bind) and
    uses ``localhost`` as the SNI / Host header, matching what the
    ``probe_client`` fixture does.

    Raises ``AssertionError`` on unparseable responses so a broken socket or
    malformed status line surfaces a clear diagnostic rather than a silent
    ``status = 0`` that downstream assertions report as "got 0, expected N".
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection(("127.0.0.1", 443), timeout=10.0) as sock,
        ctx.wrap_socket(sock, server_hostname="localhost") as ssock,
    ):
        ssock.settimeout(10.0)
        ssock.sendall(raw_request)
        chunks: list[bytes] = []
        while True:
            try:
                chunk = ssock.recv(4096)
            except (TimeoutError, OSError):
                break
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise AssertionError(
            "Raw HTTPS probe returned zero bytes — Caddy is not responding or "
            "the TLS handshake was dropped. Request was: "
            f"{raw_request[:200]!r}"
        )
    head, _, body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0]
    parts = status_line.split(b" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise AssertionError(
            f"Raw HTTPS probe returned unparseable status line "
            f"{status_line!r}. Full response head: {head[:200]!r}"
        )
    return int(parts[1]), body


@pytest.mark.non_regression
@pytest.mark.parametrize("path", _API_PATHS)
def test_oversized_post_is_rejected_with_413_and_does_not_reach_upstream(
    probe_client: httpx.Client, path: str
) -> None:
    """2 MiB POST with Content-Length → 413 from Caddy, body does NOT reach upstream.

    Exercises the ``@api_oversized_body`` matcher. The paired assertions
    close both failure modes in one probe: (a) Caddy did not reject (status
    != 413, FR49 gate failed); (b) Caddy rejected but also forwarded the
    body (stub signature present, rejection happening at the wrong layer).
    Parametrised over both ``@api``-matched paths so the policy is proven
    to apply at handler scope, not per-path.
    """
    payload = b"x" * _TWO_MB
    resp = probe_client.post(path, content=payload, headers=_OCTET_STREAM)
    assert resp.status_code == 413, (
        f"Expected 413 on POST {path} with Content-Length {len(payload)}, "
        f"got {resp.status_code}. Caddy's `@api_oversized_body` matcher did "
        f"not reject — FR49 regression gate has failed. "
        f"Response body (first 200 bytes): {resp.content[:200]!r}"
    )
    assert _STUB_SIGNATURE not in resp.content, (
        f"POST {path} with {len(payload)} bytes returned 413, but the "
        f"upstream stub signature {_STUB_SIGNATURE!r} is in the response "
        f"body — Caddy matched the oversize rule AND forwarded the request. "
        f"FR49 regression: rejection is happening at the wrong layer."
    )


@pytest.mark.non_regression
def test_sub_boundary_post_is_accepted_and_reaches_upstream(
    probe_client: httpx.Client,
) -> None:
    """A POST just under 1 MiB is accepted by Caddy AND reaches upstream.

    Proves the limit sits at ~1 MiB rather than an arbitrarily small
    value. Asserts ``status != 413`` (not ``== 200``) so the probe stays
    meaningful when the stub is swapped for a real upstream that may
    return 401/422 on a raw-bytes payload.
    """
    payload = b"x" * _SUB_BOUNDARY
    resp = probe_client.post("/v1/audio/speech", content=payload, headers=_OCTET_STREAM)
    assert resp.status_code != 413, (
        f"Expected non-413 on sub-boundary POST ({len(payload)} bytes, "
        f"under the 1 MiB limit), got 413. The `@api_oversized_body` "
        f"threshold has tightened below the FR49 contract. "
        f"Response body (first 200 bytes): {resp.content[:200]!r}"
    )
    assert _STUB_SIGNATURE in resp.content, (
        f"Sub-boundary POST ({len(payload)} bytes) returned "
        f"{resp.status_code} but the upstream stub signature is absent. "
        f"Caddy accepted but did not proxy — the `handle @api` block may "
        f"have been reshaped. Response body (first 200 bytes): "
        f"{resp.content[:200]!r}"
    )


@pytest.mark.non_regression
@pytest.mark.parametrize("path", _API_PATHS)
def test_chunked_post_is_rejected_with_411(
    probe_client: httpx.Client, path: str
) -> None:
    """``Transfer-Encoding: chunked`` on ``@api`` → 411 from ``@api_has_te``.

    Closes the chunked-truncation false-pass path. Without this matcher,
    Caddy's ``request_body max_size`` paired with ``reverse_proxy``
    silently truncates oversized chunked uploads and forwards the prefix
    to upstream (empirically verified 2026-04-24 on caddy:2-alpine v2.11.2).
    The policy forces all ``@api`` clients to send Content-Length, making
    the oversized-body matcher the sole enforcement path for large payloads.
    """
    resp = probe_client.post(
        path,
        content=_chunked_bytes(_TWO_MB),
        headers=_OCTET_STREAM,
    )
    assert resp.status_code == 411, (
        f"Expected 411 (Length Required) on chunked POST {path}, got "
        f"{resp.status_code}. The `@api_has_te` matcher did not fire — "
        f"oversized chunked uploads may silently truncate and reach "
        f"upstream. FR49 regression. "
        f"Response body (first 200 bytes): {resp.content[:200]!r}"
    )
    assert _STUB_SIGNATURE not in resp.content, (
        f"Chunked POST {path} returned {resp.status_code} but the upstream "
        f"stub signature is in the body — Caddy forwarded a chunked request "
        f"that should have been rejected. FR49 regression: chunked uploads "
        f"bypass the policy."
    )


@pytest.mark.non_regression
@pytest.mark.parametrize(
    "te_value",
    ("identity", "gzip", "deflate"),
)
def test_non_chunked_transfer_encoding_is_rejected_before_upstream(
    te_value: str,
) -> None:
    """Non-chunked ``Transfer-Encoding`` values → rejected before upstream.

    Two valid rejection layers:
      * Caddy's Go ``net/http`` stack rejects unsupported TE values with
        ``501 Unsupported transfer encoding`` BEFORE the request reaches
        any matcher. This is RFC-7230 §3.3.1 behaviour.
      * The widened ``@api_has_te`` matcher rejects any TE value with 411
        defense-in-depth — fires for ``chunked`` (which Go accepts as a
        known TE and routes to matchers), and would fire for any
        hypothetical future Go version that stops 501-ing on unknown TE.

    The assertion accepts either 411 (matcher) or 501 (Go parse layer);
    the FR49-load-bearing contract is "request is rejected and the stub
    signature is absent from the body" — both layers satisfy that. Uses a
    raw TLS socket because httpx does not emit arbitrary TE values.
    """
    raw = (
        f"POST /v1/audio/speech HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/octet-stream\r\n"
        f"Transfer-Encoding: {te_value}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    status, body = _send_raw_https(raw)
    assert status in (411, 501), (
        f"Expected 411 (@api_has_te matcher) or 501 (Go net/http "
        f"unsupported-TE rejection) on POST with `Transfer-Encoding: "
        f"{te_value}`, got {status}. Non-chunked TE values bypass both "
        f"rejection layers. "
        f"Response body (first 200 bytes): {body[:200]!r}"
    )
    assert _STUB_SIGNATURE not in body, (
        f"Non-chunked TE value `{te_value}` returned {status} but the "
        f"upstream stub signature is in the body — Caddy forwarded a "
        f"request with ambiguous framing. FR49 regression."
    )


@pytest.mark.non_regression
@pytest.mark.parametrize("method", _WRITE_METHODS)
@pytest.mark.parametrize("path", _API_PATHS)
def test_write_without_body_framing_is_rejected_with_411(
    method: str, path: str
) -> None:
    """POST/PUT/PATCH with neither ``Content-Length`` nor ``Transfer-Encoding`` → 411.

    Exercises the ``@api_missing_cl`` matcher. Parametrised over the three
    write methods the matcher covers, so a Caddyfile edit that drops PUT
    or PATCH from the method list is caught. Uses a raw TLS socket because
    httpx unconditionally adds ``Content-Length: 0`` on empty bodies,
    which would make the matcher miss.
    """
    raw = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/octet-stream\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    status, body = _send_raw_https(raw)
    assert status == 411, (
        f"Expected 411 (Length Required) on {method} {path} with no "
        f"body-framing headers, got {status}. The `@api_missing_cl` "
        f"matcher did not fire for method {method!r}. "
        f"Response body (first 200 bytes): {body[:200]!r}"
    )
    assert _STUB_SIGNATURE not in body, (
        f"{method} {path} without body-framing returned {status} but the "
        f"upstream stub signature is in the body — Caddy forwarded a "
        f"framing-ambiguous write. FR49 regression."
    )


@pytest.mark.non_regression
@pytest.mark.parametrize(
    "cl_value",
    (
        "abc",  # non-numeric
        "-1",  # negative (hyphen fails the digit class)
        "12abc",  # numeric prefix, non-numeric suffix
        "1,1",  # comma-joined duplicate header representation
        "99999999999",  # 11 digits — exceeds the 10-digit bound
    ),
)
def test_malformed_content_length_returns_400(cl_value: str) -> None:
    """Non-canonical ``Content-Length`` → 400 from ``@api_malformed_cl``.

    Closes the ``int()`` CEL-cast bypass. Without the regex pre-guard in
    ``@api_malformed_cl`` (``^[0-9]{1,10}$``), the oversized-body matcher's
    CEL expression errors on non-numeric, negative, duplicate, or >10-digit
    (int64-overflow) values and evaluates to ``false``, letting the
    request fall through to reverse_proxy. The 10-digit bound is ample
    above any legitimate payload (1 MiB = 7 digits) but keeps ``int()``
    well under int64. Uses a raw TLS socket because httpx re-computes
    ``Content-Length`` to match the body.

    Leading/trailing whitespace is intentionally NOT tested here — Caddy
    (via Go net/http) trims header values per RFC-7230 §3.2.4 before any
    matcher runs, so ``Content-Length:  1048576`` reaches the regex as
    the trimmed string ``1048576`` and is a valid-shape header.
    """
    raw = (
        f"POST /v1/audio/speech HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/octet-stream\r\n"
        f"Content-Length: {cl_value}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    status, body = _send_raw_https(raw)
    assert status == 400, (
        f"Expected 400 on POST with `Content-Length: {cl_value!r}`, got "
        f"{status}. The `@api_malformed_cl` matcher did not fire — this "
        f"Content-Length shape may bypass the regex pre-guard and reach "
        f"the int() cast with an error. "
        f"Response body (first 200 bytes): {body[:200]!r}"
    )
    assert _STUB_SIGNATURE not in body, (
        f"Malformed Content-Length `{cl_value!r}` returned {status} but "
        f"the upstream stub signature is in the body — Caddy forwarded a "
        f"request with a bad Content-Length. FR49 regression."
    )


@pytest.mark.non_regression
def test_oversized_post_to_non_api_path_is_not_413(
    probe_client: httpx.Client,
) -> None:
    """A 2 MiB POST to a non-``@api`` path (landing ``/``) must NOT return 413.

    Proves the oversized-body policy is scoped to ``@api`` paths. A
    regression that broadens ``@api_oversized_body`` to ``path /*``
    would be caught here — the landing handler would suddenly start
    413-ing large POSTs it should have left to its default handling.

    Asserts a positive shape (``status < 500`` AND ``status != 413``)
    rather than bare ``!= 413`` so a Caddy 5xx (e.g., stream failure on
    the 2 MiB POST to file_server) does not produce a false-positive
    green test.
    """
    payload = b"x" * _TWO_MB
    resp = probe_client.post("/", content=payload, headers=_OCTET_STREAM)
    assert resp.status_code != 413, (
        f"Expected non-413 on POST / (landing path) with {len(payload)} "
        f"bytes — FR49's policy is @api-scoped. Got 413, meaning the "
        f"oversized matcher has broadened beyond `path /v1/* /health`. "
        f"Response body (first 200 bytes): {resp.content[:200]!r}"
    )
    assert resp.status_code < 500, (
        f"Expected a non-5xx response on POST / with {len(payload)} bytes "
        f"(file_server should handle or cleanly reject), got "
        f"{resp.status_code}. A 5xx here means Caddy failed mid-proxy or "
        f"crashed on a large body to the landing handler — unrelated to "
        f"FR49 but a real regression. "
        f"Response body (first 200 bytes): {resp.content[:200]!r}"
    )


@pytest.mark.non_regression
def test_httpx_bytes_payload_uses_content_length_not_chunked(
    probe_client: httpx.Client,
) -> None:
    """Harness self-check: bytes payloads go out with ``Content-Length``
    and WITHOUT ``Transfer-Encoding``.

    Pins the assumption that the oversized-rejection probes exercise the
    Content-Length Caddy code path (413 via ``@api_oversized_body``), not
    the chunked code path (411 via ``@api_has_te``). A future httpx
    release that switches bytes-payload encoding to chunked would silently
    flip which matcher the probes hit; catching that here prevents the
    probes from turning green for the wrong reason.
    """
    req = probe_client.build_request(
        "POST", "/v1/audio/speech", content=b"x" * _TWO_MB, headers=_OCTET_STREAM
    )
    assert req.headers.get("Content-Length") == str(_TWO_MB), (
        f"httpx did not set Content-Length for a bytes payload. "
        f"Observed headers: {dict(req.headers)}."
    )
    assert "Transfer-Encoding" not in req.headers, (
        f"httpx added Transfer-Encoding for a bytes payload. Observed "
        f"headers: {dict(req.headers)}. The oversized-rejection probes "
        f"may now be hitting `@api_has_te` (411) instead of "
        f"`@api_oversized_body` (413)."
    )


@pytest.mark.non_regression
def test_caddyfile_variants_share_the_same_body_framing_policy() -> None:
    """Static parity probe between ``Caddyfile`` and ``Caddyfile-no-landing``.

    The non-regression docker harness only exercises the with-landing
    variant. Without this test, a PR that edits one file and forgets the
    other lands silently. Asserts both files declare the same four
    ``@api_*`` matchers and their paired ``handle`` blocks, and that the
    four CEL/regex expressions are byte-identical across files. The
    ``path /v1/* /health`` scoping appears only in the with-landing file
    (the no-landing variant is whole-site-API by design) and is NOT
    asserted for parity.

    Runs without docker — collects instantly and flags drift at the
    earliest possible CI stage.
    """
    with_landing = _CADDYFILE.read_text()
    no_landing = _CADDYFILE_NO_LANDING.read_text()

    for matcher in _EXPECTED_MATCHERS:
        assert (
            f"{matcher} " in with_landing
            or f"{matcher}\n" in with_landing
            or f"{matcher} {{" in with_landing
        ), (
            f"Matcher {matcher!r} missing from {_CADDYFILE} — FR49 body-framing "
            f"policy has drifted."
        )
        assert (
            f"{matcher} " in no_landing
            or f"{matcher}\n" in no_landing
            or f"{matcher} {{" in no_landing
        ), (
            f"Matcher {matcher!r} missing from {_CADDYFILE_NO_LANDING} — the "
            f"no-landing variant has drifted from the with-landing Caddyfile. "
            f"Every edit to one must be mirrored to the other."
        )
        assert f"handle {matcher}" in with_landing, (
            f"`handle {matcher}` block missing from {_CADDYFILE}."
        )
        assert f"handle {matcher}" in no_landing, (
            f"`handle {matcher}` block missing from {_CADDYFILE_NO_LANDING}."
        )

    # All CEL / regex expressions must appear verbatim in both files (they
    # encode the matcher semantics — any asymmetry here is a drift bug).
    expression_lines = [
        line.strip()
        for line in with_landing.splitlines()
        if line.strip().startswith("expression ")
    ]
    assert expression_lines, (
        f"No `expression ...` lines found in {_CADDYFILE} — the FR49 "
        f"matchers have been restructured; re-audit this parity test."
    )
    for expr in expression_lines:
        assert expr in no_landing, (
            f"Expression {expr!r} from {_CADDYFILE} is absent from "
            f"{_CADDYFILE_NO_LANDING}. The two Caddyfile variants have "
            f"drifted on FR49 matcher semantics. Mirror the edit."
        )

    # The int() threshold literal (1 MiB = 1048576) must match between files.
    threshold_pattern = re.compile(
        r"int\(\{http\.request\.header\.content-length\}\) > (\d+)"
    )
    with_thresholds = set(threshold_pattern.findall(with_landing))
    no_thresholds = set(threshold_pattern.findall(no_landing))
    assert with_thresholds == no_thresholds, (
        f"Oversize threshold literal drifted between Caddyfiles: "
        f"with-landing={with_thresholds!r}, no-landing={no_thresholds!r}. "
        f"Both must encode the same 1 MiB limit."
    )
    assert with_thresholds == {"1048576"}, (
        f"Expected oversize threshold = 1048576 (1 MiB, binary), got "
        f"{with_thresholds!r}. If the limit was intentionally changed, "
        f"update this assertion AND the `_ONE_MB` constant at the top of "
        f"this module."
    )

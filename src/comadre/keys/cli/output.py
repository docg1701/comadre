"""Shared rich Console singletons and rendering components for the CLI.

UX-DR6 ErrorDisplay — `render_error(title, hint)`: red-bordered Panel on stderr.
UX-DR7 ConfirmationLine — `render_confirmation(message)`: plain single line on stdout.
UX-DR1 KeyPanel — `render_key_panel(issued)`: double-border header + naked
    plaintext line (UX-DR17 copy-paste fidelity) + double-border context panel.
UX-DR9 Shared Console — singletons avoid terminal redetection between calls.
NO_COLOR compliance — rich respects the env var automatically. We do NOT set
`force_terminal=True` here — that would defeat NO_COLOR.
"""

from __future__ import annotations

from typing import Literal

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from comadre.keys.models import (
    ApiKeyListRow,
    AuditEventRow,
    BillingMode,
    CustomerDetailRow,
    CustomerListRow,
    CustomerStatus,
    IssuedKey,
    KeyDetailRow,
)

_stdout_console: Console | None = None
_stderr_console: Console | None = None

# Label column width = length of longest label ("billing mode:" / "first charge:" = 13).
_LABEL_WIDTH = 13

# Shared --format choices for list-customers / list-keys (UX-DR10 usage-error
# message). Hosted here so both command modules agree on the tuple identity.
LIST_FORMAT_CHOICES: tuple[str, ...] = ("table", "json")


def stdout_console() -> Console:
    """Return the shared stdout Console (singleton)."""
    global _stdout_console
    if _stdout_console is None:
        _stdout_console = Console()
    return _stdout_console


def stderr_console() -> Console:
    """Return the shared stderr Console (singleton)."""
    global _stderr_console
    if _stderr_console is None:
        _stderr_console = Console(stderr=True)
    return _stderr_console


def render_error(message: str, hint: str) -> None:
    """UX-DR6: red-bordered Panel on stderr. Caller decides the exit code."""
    stderr_console().print(Panel(hint, title=message, border_style="red", expand=False))


def render_confirmation(message: str) -> None:
    """UX-DR7: plain single-line confirmation on stdout."""
    stdout_console().print(message)


def _format_label(label: str, value: str) -> str:
    """Return `label<padding>value` with the label right-padded to _LABEL_WIDTH."""
    return f"{label.ljust(_LABEL_WIDTH)} {value}"


def _format_brl(amount: float) -> str:
    """Format ``amount`` using Brazilian Portuguese number conventions.

    Dot is the thousands separator, comma is the decimal separator
    (e.g. 1234.56 → ``1.234,56``). Implemented without ``locale`` so the
    result is independent of the process locale / LC_ALL env.
    """
    integer, fraction = f"{amount:,.2f}".split(".")
    # Python's `,` formatter gives us `1,234` — swap to the pt-BR convention.
    integer_br = integer.replace(",", ".")
    return f"{integer_br},{fraction}"


def _context_block(issued: IssuedKey) -> str:
    """Assemble the labeled context rows for the KeyPanel."""
    rec = issued.record
    lines: list[str] = []
    lines.append(_format_label("prefix:", rec.key_prefix))
    lines.append(
        _format_label("customer:", f"{issued.customer_name} ({rec.customer_id})")
    )
    lines.append(_format_label("rate limit:", f"{rec.rate_limit_rpm}/min"))
    lines.append(_format_label("billing mode:", rec.billing_mode))

    if rec.billing_mode == "complimentary":
        lines.append(_format_label("price:", "R$ 0,00 (bundled externally)"))
        # U+2014 EM DASH (not hyphen-minus): AC2 explicit requirement.
        lines.append(_format_label("paid until:", "\u2014 (not applicable)"))
    else:
        lines.append(
            _format_label("price:", f"R$ {_format_brl(rec.price_monthly)}/month")
        )
        fc_iso = issued.first_charge_date
        if fc_iso is not None:
            n = issued.first_charge_days_free
            if n is None:
                lines.append(_format_label("first charge:", fc_iso))
            else:
                lines.append(
                    _format_label(
                        "first charge:", f"{fc_iso} ({n} days free until then)"
                    )
                )

    return "\n".join(lines)


def render_key_panel(issued: IssuedKey) -> None:
    """UX-DR1 + UX-DR17: one-shot key display with copy-friendly plaintext.

    Industry-standard three-piece layout (AWS IAM, GitHub PAT, Stripe):
      1. Double-border Panel with title "API KEY (copy now — shown only once)"
         and a short warning body.
      2. The plaintext as a naked line (column 0, no border chars, no label, no
         wrapping) so triple-click selects only the key (UX-DR17). The plaintext
         is deliberately OUTSIDE any panel — wrapping it inside a Panel would
         flank it with vertical border glyphs (``║``) that defeat triple-click.
      3. A blank line separating the plaintext from the context block.
      4. Double-border Panel with labeled context rows (prefix, customer, rate
         limit, billing mode, price, first charge / paid until).

    The `IssuedKey` dataclass is ``frozen=True, slots=True`` — the plaintext is
    typed through rather than passed as a bare ``str`` to discourage accidental
    logging.
    """
    console = stdout_console()

    warning = (
        "Copy the key below now. It is the last time it will be shown — "
        "there is no way to recover it."
    )
    console.print(
        Panel(
            warning,
            box=box.DOUBLE,
            title="API KEY (copy now — shown only once)",
            expand=False,
        )
    )

    # Naked plaintext line at column 0 — UX-DR17 copy-paste fidelity.
    # - ``highlight=False`` + ``markup=False`` keeps the output a plain ASCII
    #   run with no ANSI noise.
    # - ``no_wrap=True`` + ``overflow="ignore"`` + ``crop=False`` ensure the
    #   53-char plaintext stays on a single line even on terminals narrower
    #   than 53 columns; wrapping would break triple-click selection.
    console.print(
        issued.plaintext,
        highlight=False,
        markup=False,
        no_wrap=True,
        overflow="ignore",
        crop=False,
    )

    # Blank line between the plaintext and the context panel so the copyable
    # key has breathing room above the metadata rows.
    console.print("")

    console.print(
        Panel(
            _context_block(issued),
            box=box.DOUBLE,
            expand=False,
        )
    )


def _status_label(status: CustomerStatus, billing_mode: BillingMode) -> tuple[str, str]:
    """Return ``(text, rich_color)`` for the status cell.

    UX-DR8 is text-first with color as accelerator: the label word carries
    the meaning. ``complimentary`` blue supersedes ``active`` green because
    the blue badge is the operator-meaningful signal — it tells the reader
    "this key is bundled, not a billing target" without them having to
    cross-reference the billing_mode column.
    """
    if billing_mode == "complimentary":
        return ("complimentary", "blue")
    if status == "active":
        return ("active", "green")
    if status == "suspended":
        return ("suspended", "yellow")
    if status == "revoked":
        return ("revoked", "red")
    # Fail loudly when CustomerStatus/BillingMode grows a new literal and
    # this branch table falls out of date — a silent "" style would hide
    # the drift until a reviewer noticed missing color.
    raise ValueError(
        f"Unhandled status/billing_mode combination: {status=}, {billing_mode=}"
    )


def _iso_date(value: str | None) -> str:
    """Truncate an ISO 8601 UTC timestamp to its ``YYYY-MM-DD`` date prefix.

    Returns the em-dash ``—`` (U+2014) for NULL or malformed values. The
    slice is safe against both date-only and datetime strings because
    SQLite stores both formats with ``YYYY-MM-DD`` as the first 10
    characters; anything shorter or not shaped like an ISO date is
    rendered as the em-dash so the operator sees "no data" rather than
    a corrupted partial string.
    """
    if value is None or len(value) < 10:
        return "\u2014"
    head = value[:10]
    if (
        head[4] != "-"
        or head[7] != "-"
        or not (head[0:4].isdigit() and head[5:7].isdigit() and head[8:10].isdigit())
    ):
        return "\u2014"
    return head


def render_customer_list(title: str, rows: list[CustomerListRow]) -> None:
    """Render the ``list-customers`` StatusTable variant (no status column).

    Callers must handle the empty case via ``render_empty_state`` — this
    renderer assumes ``rows`` is non-empty so the caller's policy for
    first-run / all-purged / subsequent-empty states stays visible at
    the call site (UX-DR13).
    """
    console = stdout_console()
    table = Table(title=title, expand=False)
    table.add_column("Customer ID", justify="left", no_wrap=True)
    table.add_column("Name", justify="left")
    table.add_column("Email", justify="left")
    table.add_column("Keys", justify="right")
    table.add_column("Registered", justify="left", no_wrap=True)
    for row in rows:
        table.add_row(
            row.id,
            row.name,
            row.email,
            str(row.key_count),
            _iso_date(row.registered_at),
        )
    console.print(table)
    render_confirmation(f"{len(rows)} customers found.")


def render_key_list(title: str, rows: list[ApiKeyListRow]) -> None:
    """Render the ``list-keys`` StatusTable variant with color-coded status.

    Callers must handle the empty case via ``render_empty_state``.
    """
    console = stdout_console()
    table = Table(title=title, expand=False)
    table.add_column("Prefix", justify="left", no_wrap=True)
    table.add_column("Customer", justify="left")
    table.add_column("Status", justify="left")
    table.add_column("RPM", justify="right")
    table.add_column("Price", justify="right", no_wrap=True)
    table.add_column("Paid Until", justify="left", no_wrap=True)
    for row in rows:
        label, color = _status_label(row.status, row.billing_mode)
        status_cell = Text(label, style=color)
        rpm_cell = f"{row.rate_limit_rpm}/min"
        if row.billing_mode == "complimentary":
            price_cell = f"R$ {_format_brl(0.0)}"
        else:
            price_cell = f"R$ {_format_brl(row.price_monthly)}/month"
        paid_cell = (
            _iso_date(row.paid_until)
            if row.billing_mode != "complimentary"
            else "\u2014"
        )
        table.add_row(
            row.key_prefix,
            row.customer_name,
            status_cell,
            rpm_cell,
            price_cell,
            paid_cell,
        )
    console.print(table)
    render_confirmation(f"{len(rows)} keys found.")


def render_json(payload: list[dict[str, object]]) -> None:
    """Emit ``payload`` as pretty-printed JSON via the stdout console.

    Uses ``Console.print_json(data=...)`` so ``NO_COLOR`` / ``force_terminal``
    still apply consistently with the other render_* helpers. Empty lists
    serialize as ``[]``.
    """
    stdout_console().print_json(data=payload)


def render_empty_state(lines: list[str]) -> None:
    """Emit one or more plain informational lines via ``render_confirmation``.

    Used for the UX-DR12 / UX-DR13 "empty results are not errors" path —
    callers pass the exact lines (first-run hint, all-purged hint, or a
    single-line informational sentence) and this helper keeps the output
    policy centralized.
    """
    for line in lines:
        render_confirmation(line)


_CUSTOMER_DETAIL_LABELS: tuple[str, ...] = (
    "ID:",
    "Name:",
    "Email:",
    "Tax ID Kind:",
    "Keys:",
    "Registered:",
    "Notes:",
)

_KEY_DETAIL_LABELS: tuple[str, ...] = (
    "Prefix:",
    "Customer:",
    "Status:",
    "RPM:",
    "Price:",
    "Billing:",
    "Paid Until:",
    "Created:",
    "Last Used:",
    "Age:",
    "Notes:",
)


def _pad_label(label: str, width: int) -> str:
    """Return ``label`` right-padded to ``width`` plus a trailing space."""
    return f"{label.ljust(width)} "


def _format_last_used(value: str | None) -> str:
    """Render ``last_used_at`` as ``YYYY-MM-DD HH:MM:SS`` or ``never``."""
    if value is None:
        return "never"
    # SQLite TEXT ISO 8601 UTC form: "2026-05-12T14:23:45Z" → "2026-05-12 14:23:45".
    return value.replace("T", " ").removesuffix("Z")


def _format_age(days: int) -> str:
    """Render ``age_days`` — ``today`` for zero, ``{n} days`` otherwise."""
    if days == 0:
        return "today"
    return f"{days} days"


def render_customer_detail(row: CustomerDetailRow) -> None:
    """UX-DR3 DetailPanel — single-line border, labeled rows, no tax-ID ciphertext."""
    width = max(len(label) for label in _CUSTOMER_DETAIL_LABELS)
    lines = [
        f"{_pad_label('ID:', width)}{row.id}",
        f"{_pad_label('Name:', width)}{row.name}",
        f"{_pad_label('Email:', width)}{row.email}",
        f"{_pad_label('Tax ID Kind:', width)}{row.tax_id_kind.upper()}",
        f"{_pad_label('Keys:', width)}{row.key_count}",
        f"{_pad_label('Registered:', width)}{_iso_date(row.registered_at)}",
        f"{_pad_label('Notes:', width)}{row.notes or '\u2014'}",
    ]
    stdout_console().print(
        Panel(
            "\n".join(lines),
            title=f"Customer: {row.id}",
            box=box.ROUNDED,
            expand=False,
        )
    )


def render_key_detail(row: KeyDetailRow) -> None:
    """UX-DR3 DetailPanel for keys — color-coded status, pt-BR price, age in days."""
    width = max(len(label) for label in _KEY_DETAIL_LABELS)

    label, color = _status_label(row.status, row.billing_mode)
    status_cell = f"[{color}]{label}[/]" if color else label

    if row.billing_mode == "complimentary":
        price_cell = "R$ 0,00 (bundled externally)"
    else:
        price_cell = f"R$ {_format_brl(row.price_monthly)}/month"

    lines = [
        f"{_pad_label('Prefix:', width)}{row.key_prefix}",
        f"{_pad_label('Customer:', width)}{row.customer_name} ({row.customer_id})",
        f"{_pad_label('Status:', width)}{status_cell}",
        f"{_pad_label('RPM:', width)}{row.rate_limit_rpm}/min",
        f"{_pad_label('Price:', width)}{price_cell}",
        f"{_pad_label('Billing:', width)}{row.billing_mode}",
        f"{_pad_label('Paid Until:', width)}{_iso_date(row.paid_until)}",
        f"{_pad_label('Created:', width)}{_iso_date(row.created_at)}",
        f"{_pad_label('Last Used:', width)}{_format_last_used(row.last_used_at)}",
        f"{_pad_label('Age:', width)}{_format_age(row.age_days)}",
        f"{_pad_label('Notes:', width)}{row.notes or '\u2014'}",
    ]
    stdout_console().print(
        Panel(
            "\n".join(lines),
            title=f"Key: {row.key_prefix}",
            box=box.ROUNDED,
            expand=False,
        )
    )


def render_audit_tail(events: list[AuditEventRow]) -> None:
    """UX-DR5 AuditTail — plain indented lines under the DetailPanel.

    No panel border (this is the supplementary section); a single blank line
    separates it from the DetailPanel above. Empty result renders as the
    single literal ``  No events recorded`` per UX-DR5.
    """
    render_confirmation("")
    if not events:
        render_confirmation("  No events recorded")
        return

    render_confirmation(f"Last {len(events)} events:")
    action_width = max(len(event.action) for event in events)
    for event in events:
        timestamp = event.occurred_at.replace("T", " ").removesuffix("Z")
        action = event.action.upper().ljust(action_width)
        tail = f"  {event.details_json}" if event.details_json is not None else ""
        line = f"  {timestamp}  {action}  {event.actor}{tail}"
        # Disable Rich markup interpretation so a details_json that happens to
        # contain ``[foo]`` doesn't get eaten by Rich's console markup parser.
        stdout_console().print(line, markup=False, highlight=False)


def render_show_json(
    *,
    target_type: Literal["customer", "api_key"],
    target: dict[str, object],
    events: list[dict[str, object]] | None,
) -> None:
    """Emit the AC8 single-object JSON envelope via the shared stdout console.

    ``events=None`` omits the ``events`` key entirely — distinct from an
    empty-list emission triggered by ``--audit-tail N`` returning zero rows.
    """
    payload: dict[str, object] = {"target_type": target_type, "target": target}
    if events is not None:
        payload["events"] = events
    stdout_console().print_json(data=payload)


def _reset_for_tests() -> None:
    """Test-only hook: reset console singletons so fixtures can re-wire I/O."""
    global _stdout_console, _stderr_console
    _stdout_console = None
    _stderr_console = None

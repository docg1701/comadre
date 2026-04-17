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

from rich import box
from rich.console import Console
from rich.panel import Panel

from comadre.keys.models import IssuedKey

_stdout_console: Console | None = None
_stderr_console: Console | None = None

# Label column width = length of longest label ("billing mode:" / "first charge:" = 13).
_LABEL_WIDTH = 13


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


def _reset_for_tests() -> None:
    """Test-only hook: reset console singletons so fixtures can re-wire I/O."""
    global _stdout_console, _stderr_console
    _stdout_console = None
    _stderr_console = None

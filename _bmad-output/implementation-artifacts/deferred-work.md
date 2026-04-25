# Deferred Work

Epic 4-era backlog: **empty** as of 2026-04-25.

> **Provenance:** Pruned 2026-04-25 (round 4) after the in-flight
> hardening pass closed the entire deferred-work backlog.
> Status of every item is recorded in
> `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-24.md`
> §5.3 (`[SHIPPED]` / `[NO-OP]`). The only items below the SHIPPED bar
> are F22 (NO-OP — already resolved) and F33 (Settings split, deferred
> to a dedicated tooling-pass story; tracked at the retro doc).

Future code-review findings should land directly under a new
`## Deferred from: code review of <story> (<date>)` heading below this
line.

## Deferred from: code review of 5-1-operator-ux-completion-pass (2026-04-25)

- **F-5.1.1 — `update_key` price changes are not audit-replayable in `revenue --as-of`.** `update_api_key` (`db.py:1288`) writes audit `details_json={"fields": [...]}` without old/new values, so a key whose price moved via `update-key` between `as_of` and now reports the current price in the historical snapshot. Documented limit; would require an audit-shape change to `update_key` (carry old/new for numeric fields). Low-priority: operators primarily change price via `mark-paid --price-monthly` (Story 5.1 Gap 4) which IS replayable.
- **F-5.1.2 — `export-customer --include-audit` silently truncates at 1000 rows.** Long-tenure customers with > 1000 audit events get the most-recent 1000 with no `audit_events_truncated` flag in the envelope. Add a count + truncation boolean OR raise the cap to a configurable upper bound. Operator can detect by checking `len(audit_events) == 1000` for now.
- **F-5.1.3 — `correct-tax-id` does not reject no-op corrections (same digits as stored).** Detecting this would require decrypting the stored value to compare digits, which adds a second `crypto.py::decrypt_tax_id` call site for the operator-typo guard. Trade-off: an operator who runs `correct-tax-id` with the same number burns an audit row + reason for nothing. Low frequency; defer.
- **F-5.1.4 — `_quantize_price` uses `ROUND_HALF_EVEN` (banker's), not `ROUND_HALF_UP` (Brazilian retail convention).** Edge: `100.005` → 100.00 (banker's) vs 100.01 (retail expectation). Open question: confirm with operators which semantic is preferred for monetary BRL pricing; the BRL invoice convention is half-up. Switch to `ROUND_HALF_UP` if confirmed.
- **F-5.1.5 — `mark-paid --months` uses `relativedelta`, which clamps month-end overflow to the last day of the target month.** A key with `paid_until=2026-01-31` + `--months 1` → `paid_until=2026-02-28` (28 days, not "one month later" by lay-meaning). Document explicitly in the `--months` help text OR anchor to `today` when `paid_until.day > 28`. Operator-surprising; LGPD-irrelevant.

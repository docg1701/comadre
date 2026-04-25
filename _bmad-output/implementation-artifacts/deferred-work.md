# Deferred Work

Backlog: **empty** as of 2026-04-25 (post Story 5.1 review-pass).

> **Operator policy (2026-04-25):** the deferred-work bucket is closed.
> Code-review findings must be either implemented in the same coordinated
> pass that surfaced them, or explicitly dismissed as noise / architectural
> choice (recorded in the source story's `## Review Findings` section, not
> here). This file remains as a historical pointer; do NOT add new entries.
>
> **Provenance:** Pruned 2026-04-25 (round 4) after the in-flight
> hardening pass closed the entire Epic-4 deferred-work backlog. Status
> of every item is recorded in
> `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-24.md`
> §5.3 (`[SHIPPED]` / `[NO-OP]`). The only items below the SHIPPED bar
> were F22 (NO-OP — already resolved) and F33 (Settings split, deferred
> to a dedicated tooling-pass story; tracked at the retro doc).
> The five F-5.1.x entries that briefly lived here on 2026-04-25 were
> re-triaged in `5-1-operator-ux-completion-pass.md` §Review Findings:
> F-5.1.1 / F-5.1.2 / F-5.1.4 / F-5.1.5 → patched in the review-pass;
> F-5.1.3 → dismissed (would violate the single-Fernet `crypto.py`
> invariant).

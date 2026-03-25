---
stepsCompleted:
  - step-01-document-discovery
  - step-02-prd-analysis
  - step-03-epic-coverage-validation
  - step-04-ux-alignment
  - step-05-epic-quality-review
  - step-06-final-assessment
documents:
  prd: prd.md
  architecture: architecture.md
  epics: epics.md
  ux: ux-design-specification.md
---

# Implementation Readiness Assessment Report (Post-Pivot)

**Date:** 2026-03-23
**Project:** comadre
**Context:** All planning artifacts updated after architectural pivot from KokoClone (single engine) to dual-engine architecture (Kokoro fp32 + Qwen3-TTS C++ Q8_0). This report validates alignment after the pivot.

## Document Inventory

| Document Type | File | Status |
|---|---|---|
| PRD | prd.md | Updated 2026-03-23 — dual-engine FRs/NFRs |
| Architecture | architecture.md | Updated 2026-03-23 — dual-engine decisions, routing, post-processing |
| Epics & Stories | epics.md | Updated 2026-03-23 — all stories rewritten for dual-engine |
| UX Design | ux-design-specification.md | Updated 2026-03-23 — health endpoint, voice model |
| Sprint Status | sprint-status.yaml | Updated 2026-03-23 — stories 1.4/1.5 reset to backlog, 1.6 added |
| Story 1.4 | 1-4-kokoro-tts-engine-integration.md | Kokoro TTS Engine Integration |
| Story 1.5 | 1-5-qwen3-tts-engine-integration.md | Qwen3-TTS Engine Integration |
| Research Docs | docs/*.md | Source of truth for all technical decisions |

## Key Changes from Previous Assessment

| Aspect | Previous (2026-03-21) | Current (2026-03-23) |
|---|---|---|
| TTS Engine | KokoClone (Kokoro + Kanade) | Dual: Kokoro fp32 + Qwen3-TTS C++ Q8_0 |
| Concurrency | Uvicorn multi-worker | Single FIFO queue (asyncio.Lock) |
| Performance targets | < 3s latency, 20-60 req/min | Kokoro 5-16s, Qwen3 12-37s; ~10 / ~4.8 req/min |
| FR count | 28 | 30 (added FR5a, FR5b, FR29) |
| Story count (Epic 1) | 8 | 10 (added 1.6, renumbered sequentially) |
| Stories done | 1.1-1.4 done, 1.5 review | 1.1-1.3 done, 1.4/1.5 reset to backlog |

## Coverage Validation

### FR Coverage

All 30 FRs (FR1-FR29, including FR5a and FR5b) are traceable to specific stories:

- FR1-FR5b (Audio Generation): Stories 1.4, 1.5, 1.6, 1.9
- FR6-FR10 (API Interface): Stories 1.7, 1.9
- FR11-FR13 (Health & Monitoring): Story 1.8
- FR14-FR16 (Voice Management): Stories 1.3, 1.5
- FR17-FR21 (Container & Scaling): Stories 1.9, 2.1, 2.2
- FR22-FR26 (Deployment): Stories 3.1-3.3
- FR27-FR28 (Security): Stories 2.2
- FR29 (Audio Cleanup): Story 3.3

**Coverage: 30/30 (100%)**

### NFR Coverage

All 19 NFRs updated with realistic measured values. Key changes:
- NFR1: Latency updated to Kokoro 5-16s, Qwen3 12-37s
- NFR4: Throughput updated to ~10/~4.8 req/min per instance
- NFR5: Memory updated to < 6 GB total (both engines)
- NFR11: Memory leak noted as fixed (phonemizer-fork >=3.3.2)

**Coverage: 19/19 (100%)**

### UX Alignment

- Health endpoint updated with `engines`, `queue_depth`, `clone_configured` fields
- Voice model updated from WAV-file-based discovery to engine-mapped labels
- All `workers` references replaced with queue/scaling model
- KokoClone/Kanade references removed throughout

**Alignment: Complete**

## Story Dependency Chain (Epic 1)

```
1.1 (done) → 1.2 (done) → 1.3 (done) → 1.4 (Kokoro) → 1.5 (Qwen3) → 1.6 (Router) → 1.7 → 1.8 → 1.9 → 1.10
```

Note: 1.4 and 1.5 could potentially be worked in parallel since they are independent engines. 1.6 depends on both.

## Implementation State

### Reusable from Previous Sprint

| Component | Status | Reusability |
|---|---|---|
| Project scaffolding (1.1) | done | 100% reusable |
| Config & logging (1.2) | done | 100% reusable, will need minor config additions in later stories |
| Voice discovery (1.3) | done | ~80% reusable — voice concept changes but module structure is valid |
| preprocessing.py | exists | ~60% reusable — normalize_text(), chunk_text() still needed for Kokoro. expand_siglas() is new for Qwen3 |
| service.py | exists | ~20% reusable — TTSService class structure is a starting point but engine integration changes entirely |
| exceptions.py | exists | 100% reusable — VoiceNotFoundError, GenerationError unchanged |
| Test suite (125 tests) | exists | ~40% reusable — preprocessing and config tests still valid, service tests need rewrite |

### New Components Needed

- Kokoro engine wrapper (kokoro-onnx API)
- Qwen3 engine wrapper (subprocess to qwen3-tts-cli)
- vibrato_warm post-processing pipeline (ffmpeg)
- whatsapp-subtle post-processing pipeline (ffmpeg)
- Engine routing logic
- expand_siglas() preprocessing function
- Noise WAV files
- asyncio.Lock queue in API layer
- Updated health response assembler

## Quality Findings

### Critical Violations

None.

### Major Issues

None.

### Minor Concerns

1. **pyproject.toml still references kokoclone** — Must be updated when Story 1.4 implementation begins (remove kokoclone, add kokoro-onnx)
2. **Existing service.py wraps KokoClone** — Code exists but will need significant rewrite. Should not be confused with "done" work.
3. **Story file naming** — `1-4-kokoclone-tts-service-wrapper.md` still has "kokoclone" in filename. Content is updated but filename is legacy. Renaming is optional.

## Summary

### Overall Readiness Status

**READY** — All planning artifacts are updated, aligned, and consistent with the dual-engine architecture documented in `docs/*.md`.

### Recommended Next Steps

1. Begin with **Story 1.4** (Kokoro TTS Engine Integration) — the most critical path item
2. Update `pyproject.toml` as part of Story 1.4 (replace kokoclone dep with kokoro-onnx)
3. Story 1.5 (Qwen3) can follow or run in parallel if capacity allows
4. Story 1.6 (Router) unifies both engines before proceeding to API layer stories

### Strengths

- **Deep technical research backing** — Every engine decision is supported by 400+ audio samples and measured benchmarks in `docs/*.md`
- **Partial code reuse** — Stories 1.1-1.3 are fully done and valid. preprocessing.py, exceptions.py, and test infrastructure are partially reusable
- **Clear separation** — Kokoro and Qwen3 are independent engines with independent stories, allowing parallel development
- **Realistic performance targets** — No aspirational numbers; all metrics are from measured data

**Assessor:** Implementation Readiness Validator (Post-Pivot)
**Date:** 2026-03-23

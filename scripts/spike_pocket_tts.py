# ruff: noqa: E501
"""Pocket TTS spike + tuning harness (Phase 0 deliverable — kept permanently).

Generates audio for the canonical pt-BR corpus (34 sigla phrases, WhatsApp
messages, edge cases) with the pocket-tts engine, measures RTF at different
thread/quantize settings, times clone-state encoding for 5/10/20 s references,
and emits a markdown report. Optional --baseline-dir lists the captured v2
outputs side by side for human listening A/B.

The corpus is the extraction target of the migration plan Phase 0 — the v2
feasibility artifacts (tests/test_feasibility.py, scripts/feasibility_test.py)
were deleted after their phrases were moved here.

Usage:
    uv run python scripts/spike_pocket_tts.py \\
        --config deploy/pocket-tts/portuguese.yaml \\
        --output-dir tmp/spike --threads 4 --sigla-spacing on
    uv run python scripts/spike_pocket_tts.py --config ... --quantize
    uv run python scripts/spike_pocket_tts.py --config ... --clone-timing
"""

from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import torch

from comadre.preprocessing import expand_siglas, normalize_text

# 34 sigla phrases — canonical corpus (19 verified from the v2 dictionary
# dictionary doc + 15 from pt_extra / pt_list built-ins).
SIGLAS = [
    "CPF",
    "CNPJ",
    "RG",
    "CNH",
    "STF",
    "STJ",
    "TRT",
    "TRF",
    "TST",
    "BPC",
    "CLT",
    "CTPS",
    "FGTS",
    "SUS",
    "PIX",
    "DETRAN",
    "ENEM",
    "SAMU",
    "ANVISA",
    "INSS",
    "IPVA",
    "IPTU",
    "IRPF",
    "OAB",
    "TSE",
    "UBS",
    "MEI",
    "CEP",
    "IBGE",
    "IPCA",
    "IGPM",
    "BNDES",
    "CAIXA",
    "URL",
]

SIGLA_PHRASES = [
    (f"sigla-{i:02d}-{s.lower()}", f"O {s} é importante para o processo.")
    for i, s in enumerate(SIGLAS, start=1)
]

WHATSAPP_PHRASES = [
    (
        "ws-01",
        "Olá! Bem-vindo ao atendimento da Loja Virtual. Como posso ajudar você hoje?",
    ),
    (
        "ws-02",
        "Seu pedido número 4587 foi enviado em 19/03/2026 e deve chegar até 25/03/2026.",
    ),
    ("ws-03", "O valor total da sua compra ficou em R$ 247,90 com frete grátis."),
    ("ws-04", "Nosso horário de atendimento é das 08:00 às 18:00 de segunda a sexta."),
    ("ws-05", "Vou transferir você para o setor financeiro. Um momento, por favor."),
    (
        "ws-06",
        "Infelizmente esse produto está fora de estoque. Posso sugerir uma alternativa?",
    ),
    ("ws-07", "Seu reembolso de R$ 89,90 será processado em até 5 dias úteis."),
    (
        "ws-08",
        "Para acompanhar seu pedido, acesse nosso site com o código de rastreio BR123456789.",
    ),
    (
        "ws-09",
        "Agradecemos seu contato! Tem mais alguma dúvida que eu possa esclarecer?",
    ),
    (
        "ws-10",
        "Entendi sua reclamação. Já registrei o protocolo número 20260321 para acompanhamento.",
    ),
]

EDGE_PHRASES = [
    ("edge-01", "Sim"),
    ("edge-02", "R$ 0,01"),
    ("edge-03", "R$ 999.999,99"),
    ("edge-04", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    (
        "edge-06",
        "João comprou 3 abacaxis, 12 bananas e 1 melancia por R$ 45,00 no dia 15/06/2026 às 09:30",
    ),
    ("edge-07", "hahaha kkkkkk rsrsrs"),
    (
        "edge-08",
        "São Paulo, Rio de Janeiro, Belo Horizonte, Porto Alegre e Florianópolis são capitais.",
    ),
]

LONG_TEXT = (
    "O Brasil é o maior país da América do Sul, com uma população de mais de 200 milhões de habitantes. "
    "Sua capital é Brasília, fundada em 21/04/1960. "
    "O país tem 26 estados e um Distrito Federal. "
    "A economia brasileira é a maior da América Latina, com um PIB de aproximadamente R$ 10.000.000.000.000,00. "
    "O horário de Brasília é baseado no fuso horário de menos três horas em relação a Greenwich. "
    "As principais cidades incluem São Paulo, Rio de Janeiro, Salvador, Fortaleza e Belo Horizonte. "
    "A temperatura média anual varia de 16 graus no sul a 28 graus no norte do país. "
    "O Brasil possui a maior floresta tropical do mundo, a Amazônia, que cobre aproximadamente 5.500.000 quilômetros quadrados. "
    "A língua oficial é o português, falado por 100% da população."
)


@dataclass
class RunResult:
    name: str
    text: str
    preprocessed: str
    gen_time_s: float
    audio_duration_s: float
    rtf: float
    output_path: str


def preprocess(text: str, sigla_spacing: bool) -> str:
    """Apply the v3 preprocessing chain: normalize_text + optional siglas."""
    normalized = normalize_text(text)
    if sigla_spacing:
        normalized = expand_siglas(normalized)
    return normalized


def generate_and_save(
    model: object,
    state: dict[str, dict[str, torch.Tensor]],
    name: str,
    text: str,
    output_dir: Path,
    sigla_spacing: bool,
) -> RunResult:
    """Generate one utterance, save as WAV, return timing metrics."""
    pre = preprocess(text, sigla_spacing)
    t0 = time.perf_counter()
    audio: torch.Tensor = model.generate_audio(state, pre, copy_state=True)  # type: ignore[attr-defined]
    gen_time = time.perf_counter() - t0
    duration = audio.shape[-1] / model.sample_rate  # type: ignore[attr-defined]
    out_path = output_dir / f"{name}.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import scipy.io.wavfile

    samples = audio.numpy().T  # [samples, channels]
    scipy.io.wavfile.write(str(out_path), model.sample_rate, samples)  # type: ignore[attr-defined]
    return RunResult(
        name=name,
        text=text,
        preprocessed=pre,
        gen_time_s=gen_time,
        audio_duration_s=duration,
        rtf=gen_time / duration if duration > 0 else float("inf"),
        output_path=str(out_path),
    )


def run_corpus(
    model: object,
    default_state_path: Path,
    items: list[tuple[str, str]],
    output_dir: Path,
    sigla_spacing: bool,
) -> list[RunResult]:
    """Run a corpus against the default (rafael) state."""
    from pocket_tts import TTSModel

    state = TTSModel.get_state_for_audio_prompt(model, default_state_path)  # type: ignore[attr-defined]
    results: list[RunResult] = []
    for name, text in items:
        print(f"[{name}] {text[:60]}")
        results.append(
            generate_and_save(model, state, name, text, output_dir, sigla_spacing)
        )
    return results


def clone_timing(model: object, output_dir: Path, rafael_state_path: Path) -> None:
    """Time clone-state encoding for 5/10/20 s reference WAVs.

    Synthesizes a long utterance with the rafael state, slices it into
    5/10/20 s reference WAVs, then measures get_state_for_audio_prompt
    for each slice and reports the state size (about 3 MB per 5 s for the
    6-layer model).
    """
    import scipy.io.wavfile
    from pocket_tts import TTSModel

    state = TTSModel.get_state_for_audio_prompt(model, rafael_state_path)  # type: ignore[attr-defined]
    long_audio = model.generate_audio(state, LONG_TEXT, copy_state=True)  # type: ignore[attr-defined]
    sr = model.sample_rate  # type: ignore[attr-defined]
    samples = long_audio.numpy().T

    refs: list[tuple[str, int]] = [("5s", 5), ("10s", 10), ("20s", 20)]
    rows: list[str] = []
    for label, seconds in refs:
        n = min(seconds * sr, samples.shape[0])
        ref_path = output_dir / f"ref-{label}.wav"
        scipy.io.wavfile.write(str(ref_path), sr, samples[:n])
        t0 = time.perf_counter()
        clone_state = TTSModel.get_state_for_audio_prompt(  # type: ignore[attr-defined]
            model, ref_path, truncate=True
        )
        encode_s = time.perf_counter() - t0
        size_mb = (
            sum(
                t.numel() * t.element_size()
                for m in clone_state.values()
                for t in m.values()
            )
            / 1e6
        )
        rows.append(f"| {label} | {encode_s:.2f}s | {size_mb:.1f} MB |")
        print(f"clone encode {label}: {encode_s:.2f}s, state {size_mb:.1f} MB")
    (output_dir / "clone-timing.md").write_text(
        "| Ref duration | Encode time | State size |\n|---|---|---|\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def write_report(
    output_dir: Path,
    results: list[RunResult],
    sigla_spacing: bool,
    model: object,
) -> None:
    """Write a markdown report with RTF metrics."""
    rows = [
        f"| {r.name} | {r.text[:40]} | {r.preprocessed[:50]} | "
        f"{r.audio_duration_s:.1f}s | {r.gen_time_s:.1f}s | {r.rtf:.2f} |"
        for r in results
    ]
    rtfs = [r.rtf for r in results if r.rtf != float("inf")]
    summary = (
        f"items={len(results)} mean_rtf={statistics.mean(rtfs):.2f} "
        f"median_rtf={statistics.median(rtfs):.2f} max_rtf={max(rtfs):.2f} "
        f"total_gen={sum(r.gen_time_s for r in results):.0f}s "
        f"total_audio={sum(r.audio_duration_s for r in results):.1f}s"
    )
    report = (
        f"# Pocket TTS spike report\n\n"
        f"sigla_spacing={sigla_spacing} sample_rate={model.sample_rate}\n\n"  # type: ignore[attr-defined]
        f"{summary}\n\n"
        "| ID | Text | Preprocessed | Dur | Gen | RTF |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"\n{summary}")
    print(f"Report: {output_dir / 'report.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pocket TTS spike/tuning harness")
    parser.add_argument(
        "--config",
        default="deploy/pocket-tts/portuguese.yaml",
        help="Path to the pocket-tts config YAML (default: deploy/pocket-tts/portuguese.yaml)",
    )
    parser.add_argument(
        "--default-voice-path",
        default="models/pocket-tts/portuguese/embeddings/rafael.safetensors",
        help="Path to the default catalog voice state (rafael)",
    )
    parser.add_argument("--output-dir", default="tmp/spike")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--quantize", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--sigla-spacing",
        choices=["on", "off"],
        default="on",
        help="Apply expand_siglas (spaced letters) — the sigla quality lever",
    )
    parser.add_argument(
        "--clone-timing",
        action="store_true",
        help="Time clone-state encoding for 5/10/20 s references",
    )
    parser.add_argument(
        "--baseline-dir",
        default=None,
        help="v2 baseline dir (tmp/v2-baseline) — prints A/B listening pairs",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads)

    # Import AFTER torch thread config; the pocket_tts import calls
    # torch.set_num_threads(1) upstream — we override it again here.
    from pocket_tts import TTSModel

    torch.set_num_threads(args.threads)
    print(
        f"Loading model (config={args.config}, threads={args.threads}, "
        f"quantize={args.quantize}, temp={args.temperature})"
    )
    model = TTSModel.load_model(
        config=args.config, quantize=args.quantize, temp=args.temperature
    )
    print(f"Loaded; sample_rate={model.sample_rate}")

    default_state_path = Path(args.default_voice_path)
    if not default_state_path.is_file():
        print(f"WARNING: default voice state not found: {default_state_path}")
        default_state_path = None  # type: ignore[assignment]

    sigla_spacing = args.sigla_spacing == "on"

    results: list[RunResult] = []
    results += run_corpus(
        model, default_state_path, SIGLA_PHRASES, output_dir / "siglas", sigla_spacing
    )
    results += run_corpus(
        model,
        default_state_path,
        WHATSAPP_PHRASES,
        output_dir / "whatsapp",
        sigla_spacing,
    )
    results += run_corpus(
        model, default_state_path, EDGE_PHRASES, output_dir / "edge", sigla_spacing
    )
    write_report(output_dir, results, sigla_spacing, model)

    if args.clone_timing:
        clone_timing(model, output_dir / "clone", default_state_path)

    if args.baseline_dir:
        base = Path(args.baseline_dir)
        print("\n=== A/B listening pairs (v2 baseline vs pocket spike) ===")
        for r in results:
            v2_ogg = base / Path(r.output_path).relative_to(output_dir).with_suffix(
                ".ogg"
            )
            print(
                f"v2: {v2_ogg if v2_ogg.is_file() else '(missing)'}  |  v3: {r.output_path}"
            )


if __name__ == "__main__":
    main()

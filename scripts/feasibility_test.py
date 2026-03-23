# ruff: noqa: E501,E402,PTH112
"""CUMADRE Feasibility Test: pt-BR TTS quality and performance evaluation.

Generates real audio files for human listening evaluation and produces
a markdown report with timing metrics.

Usage:
    uv run python scripts/feasibility_test.py
    uv run python scripts/feasibility_test.py --categories A,C,D
    uv run python scripts/feasibility_test.py --ref tmp/audio-referencia-02.wav
"""

from __future__ import annotations

# Resource limits MUST be set before any torch/onnx imports
import os

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "4")

# Use compiled espeak-ng data with PR #2344 pt-BR improvements
ESPEAK_DATA_COMPILED = "/tmp/espeak-ng-install/share/espeak-ng-data"
if os.path.isdir(ESPEAK_DATA_COMPILED):
    os.environ["ESPEAK_DATA_PATH"] = ESPEAK_DATA_COMPILED

import argparse
import dataclasses
import platform
import resource
import statistics
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TestCase:
    id: str
    category: str
    text: str
    description: str
    preprocess: bool
    use_cloning: bool = True
    voice_name: str | None = None  # for built-in voice tests


@dataclasses.dataclass
class TestResult:
    test_case: TestCase
    output_path: str
    generation_time_s: float
    audio_duration_s: float
    rtf: float
    phonemes: str
    preprocessed_text: str
    error: str | None = None
    rss_mb: float = 0.0


# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------

CATEGORY_A: list[TestCase] = [
    TestCase(
        "raw-01",
        "01-raw-espeak",
        "O pedido custa R$ 1.500,00",
        "Currency symbols",
        preprocess=False,
    ),
    TestCase(
        "raw-02",
        "01-raw-espeak",
        "Entrega em 21/03/2026",
        "Date digits",
        preprocess=False,
    ),
    TestCase(
        "raw-03", "01-raw-espeak", "Reunião às 14:30", "Time digits", preprocess=False
    ),
    TestCase(
        "raw-04",
        "01-raw-espeak",
        "São 42 itens no 3º lote",
        "Integers + ordinals",
        preprocess=False,
    ),
    TestCase(
        "raw-05",
        "01-raw-espeak",
        "O café está quente",
        "Open vowel e",
        preprocess=False,
    ),
    TestCase(
        "raw-06",
        "01-raw-espeak",
        "A avó fez bolo para o avô",
        "Open/close vowel o",
        preprocess=False,
    ),
    TestCase(
        "raw-07",
        "01-raw-espeak",
        "Rúben assinou a rubrica",
        "Stress position",
        preprocess=False,
    ),
]

CATEGORY_B: list[TestCase] = [
    TestCase(
        "pre-01",
        "02-preprocessed",
        "O pedido custa R$ 1.500,00",
        "Currency preprocessed",
        preprocess=True,
    ),
    TestCase(
        "pre-02",
        "02-preprocessed",
        "Entrega em 21/03/2026",
        "Date preprocessed",
        preprocess=True,
    ),
    TestCase(
        "pre-03",
        "02-preprocessed",
        "Reunião às 14:30",
        "Time preprocessed",
        preprocess=True,
    ),
    TestCase(
        "pre-04",
        "02-preprocessed",
        "São 42 itens no 3º lote",
        "Numbers preprocessed",
        preprocess=True,
    ),
]

VOICE_PHRASE = "Olá! Meu nome é Ana e estou aqui para ajudar você com seu pedido."

CATEGORY_C: list[TestCase] = [
    TestCase(
        "voice-ref01",
        "03-voice-comparison",
        VOICE_PHRASE,
        "Cloned ref-01",
        preprocess=True,
        use_cloning=True,
    ),
    TestCase(
        "voice-ref02",
        "03-voice-comparison",
        VOICE_PHRASE,
        "Cloned ref-02",
        preprocess=True,
        use_cloning=True,
    ),
    TestCase(
        "voice-dora",
        "03-voice-comparison",
        VOICE_PHRASE,
        "Built-in pf_dora",
        preprocess=True,
        use_cloning=False,
        voice_name="pf_dora",
    ),
    TestCase(
        "voice-alex",
        "03-voice-comparison",
        VOICE_PHRASE,
        "Built-in pm_alex",
        preprocess=True,
        use_cloning=False,
        voice_name="pm_alex",
    ),
    TestCase(
        "voice-santa",
        "03-voice-comparison",
        VOICE_PHRASE,
        "Built-in pm_santa",
        preprocess=True,
        use_cloning=False,
        voice_name="pm_santa",
    ),
]

CATEGORY_D: list[TestCase] = [
    TestCase(
        "ws-01",
        "04-whatsapp-dialogue",
        "Olá! Bem-vindo ao atendimento da Loja Virtual. Como posso ajudar você hoje?",
        "Greeting",
        preprocess=True,
    ),
    TestCase(
        "ws-02",
        "04-whatsapp-dialogue",
        "Seu pedido número 4587 foi enviado em 19/03/2026 e deve chegar até 25/03/2026.",
        "Order status",
        preprocess=True,
    ),
    TestCase(
        "ws-03",
        "04-whatsapp-dialogue",
        "O valor total da sua compra ficou em R$ 247,90 com frete grátis.",
        "Order value",
        preprocess=True,
    ),
    TestCase(
        "ws-04",
        "04-whatsapp-dialogue",
        "Nosso horário de atendimento é das 08:00 às 18:00 de segunda a sexta.",
        "Business hours",
        preprocess=True,
    ),
    TestCase(
        "ws-05",
        "04-whatsapp-dialogue",
        "Vou transferir você para o setor financeiro. Um momento, por favor.",
        "Transfer",
        preprocess=True,
    ),
    TestCase(
        "ws-06",
        "04-whatsapp-dialogue",
        "Infelizmente esse produto está fora de estoque. Posso sugerir uma alternativa?",
        "Out of stock",
        preprocess=True,
    ),
    TestCase(
        "ws-07",
        "04-whatsapp-dialogue",
        "Seu reembolso de R$ 89,90 será processado em até 5 dias úteis.",
        "Refund",
        preprocess=True,
    ),
    TestCase(
        "ws-08",
        "04-whatsapp-dialogue",
        "Para acompanhar seu pedido, acesse nosso site com o código de rastreio BR123456789.",
        "Tracking",
        preprocess=True,
    ),
    TestCase(
        "ws-09",
        "04-whatsapp-dialogue",
        "Agradecemos seu contato! Tem mais alguma dúvida que eu possa esclarecer?",
        "Closing",
        preprocess=True,
    ),
    TestCase(
        "ws-10",
        "04-whatsapp-dialogue",
        "Entendi sua reclamação. Já registrei o protocolo número 20260321 para acompanhamento.",
        "Complaint",
        preprocess=True,
    ),
    TestCase(
        "ws-11",
        "04-whatsapp-dialogue",
        "O desconto de 15% será aplicado na sua próxima compra acima de R$ 100,00.",
        "Discount",
        preprocess=True,
    ),
    TestCase(
        "ws-12",
        "04-whatsapp-dialogue",
        "Sua consulta está agendada para 28/03/2026 às 10:30. Confirma?",
        "Appointment",
        preprocess=True,
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

CATEGORY_E: list[TestCase] = [
    TestCase("edge-01", "05-edge-cases", "Sim", "Single word", preprocess=True),
    TestCase(
        "edge-02", "05-edge-cases", "R$ 0,01", "Minimal currency", preprocess=True
    ),
    TestCase(
        "edge-03", "05-edge-cases", "R$ 999.999,99", "Large currency", preprocess=True
    ),
    TestCase(
        "edge-04",
        "05-edge-cases",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "All caps letters",
        preprocess=True,
    ),
    TestCase(
        "edge-05", "05-edge-cases", LONG_TEXT, "Long text (chunking)", preprocess=True
    ),
    TestCase(
        "edge-06",
        "05-edge-cases",
        "João comprou 3 abacaxis, 12 bananas e 1 melancia por R$ 45,00 no dia 15/06/2026 às 09:30",
        "Everything mixed",
        preprocess=True,
    ),
    TestCase(
        "edge-07",
        "05-edge-cases",
        "hahaha kkkkkk rsrsrs",
        "Internet slang",
        preprocess=True,
    ),
    TestCase(
        "edge-08",
        "05-edge-cases",
        "São Paulo, Rio de Janeiro, Belo Horizonte, Porto Alegre e Florianópolis são capitais.",
        "Proper nouns",
        preprocess=True,
    ),
]

ALL_CATEGORIES: dict[str, list[TestCase]] = {
    "A": CATEGORY_A,
    "B": CATEGORY_B,
    "C": CATEGORY_C,
    "D": CATEGORY_D,
    "E": CATEGORY_E,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_wav_duration(path: str) -> float:
    """Return duration in seconds of a WAV file."""
    with wave.open(path, "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def get_rss_mb() -> float:
    """Return current RSS in MB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024  # Linux reports KB


def get_system_info() -> dict[str, str]:
    """Collect system information for the report."""
    import multiprocessing

    return {
        "platform": platform.platform(),
        "cpu": platform.processor() or "unknown",
        "cpu_count": str(multiprocessing.cpu_count()),
        "threads_limit": os.environ.get("OMP_NUM_THREADS", "unset"),
        "python": sys.version.split()[0],
        "timestamp": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


# ---------------------------------------------------------------------------
# Audio generation
# ---------------------------------------------------------------------------


def run_test_case(
    tc: TestCase,
    cloner: object,
    g2p: object,
    ref_audio: str,
    ref_audio_02: str,
    output_dir: Path,
) -> TestResult:
    """Run a single test case and return the result."""
    from cumadre.preprocessing import normalize_text

    category_dir = output_dir / tc.category
    category_dir.mkdir(parents=True, exist_ok=True)
    output_path = category_dir / f"{tc.id}.wav"

    # Preprocess
    text_to_speak = normalize_text(tc.text) if tc.preprocess else tc.text

    # Get phonemes for the report
    phonemes = ""
    try:
        result = g2p(text_to_speak)  # type: ignore[operator]
        phonemes = result[0] if result else ""
    except Exception:
        phonemes = "(phoneme extraction failed)"

    # Generate
    t0 = time.perf_counter()
    try:
        if tc.use_cloning:
            ref = ref_audio_02 if tc.id == "voice-ref02" else ref_audio
            cloner.generate(text_to_speak, "pt", ref, str(output_path))  # type: ignore[union-attr]
        else:
            # Built-in voice: use Kokoro directly without Kanade
            import soundfile as sf

            kokoro = cloner.kokoro_cache.get("model/kokoro.onnx")  # type: ignore[union-attr]
            if kokoro is None:
                return TestResult(
                    test_case=tc,
                    output_path=str(output_path),
                    generation_time_s=0,
                    audio_duration_s=0,
                    rtf=0,
                    phonemes=phonemes,
                    preprocessed_text=text_to_speak,
                    error="Kokoro cache empty — run a cloning test first",
                )
            samples, sr = kokoro.create(
                phonemes,
                voice=tc.voice_name or "pf_dora",
                speed=1.0,
                is_phonemes=True,
            )
            sf.write(str(output_path), samples, sr)

        gen_time = time.perf_counter() - t0
        duration = get_wav_duration(str(output_path))
        rtf = gen_time / duration if duration > 0 else float("inf")
        rss = get_rss_mb()

        return TestResult(
            test_case=tc,
            output_path=str(output_path),
            generation_time_s=gen_time,
            audio_duration_s=duration,
            rtf=rtf,
            phonemes=phonemes,
            preprocessed_text=text_to_speak,
            rss_mb=rss,
        )

    except Exception as exc:
        gen_time = time.perf_counter() - t0
        return TestResult(
            test_case=tc,
            output_path=str(output_path),
            generation_time_s=gen_time,
            audio_duration_s=0,
            rtf=0,
            phonemes=phonemes,
            preprocessed_text=text_to_speak,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def write_report(
    output_dir: Path,
    sys_info: dict[str, str],
    load_time: float,
    warmup_time: float,
    load_rss: float,
    results_by_category: dict[str, list[TestResult]],
) -> None:
    """Write markdown report to output_dir/report.md."""
    report_path = output_dir / "report.md"
    lines: list[str] = []

    lines.append("# CUMADRE Feasibility Test Report\n")
    lines.append(f"Generated: {sys_info['timestamp']}\n")

    lines.append("\n## System Info\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Platform | {sys_info['platform']} |")
    lines.append(f"| CPU | {sys_info['cpu']} |")
    lines.append(f"| CPU cores | {sys_info['cpu_count']} |")
    lines.append(f"| Thread limit | {sys_info['threads_limit']} |")
    lines.append(f"| Python | {sys_info['python']} |")
    lines.append("")

    lines.append("\n## Model Load\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Load time | {load_time:.1f}s |")
    lines.append(f"| Warm-up time | {warmup_time:.1f}s |")
    lines.append(f"| RSS after load | {load_rss:.0f} MB |")
    lines.append("")

    # Category tables
    category_names = {
        "A": "Category A: Raw espeak-ng (no preprocessing)",
        "B": "Category B: With Preprocessing",
        "C": "Category C: Voice Comparison",
        "D": "Category D: WhatsApp Dialogue",
        "E": "Category E: Edge Cases",
    }

    all_results: list[TestResult] = []

    for cat_key, cat_name in category_names.items():
        results = results_by_category.get(cat_key, [])
        if not results:
            continue
        all_results.extend(results)

        lines.append(f"\n## {cat_name}\n")

        if cat_key == "B":
            lines.append(
                "| ID | Original | Preprocessed | Duration | Gen Time | RTF | Phonemes |"
            )
            lines.append("|---|---|---|---|---|---|---|")
            for r in results:
                orig = r.test_case.text[:40]
                pre = r.preprocessed_text[:40]
                if r.error:
                    lines.append(
                        f"| {r.test_case.id} | {orig} | {pre} | ERROR | - | - | `{r.error}` |"
                    )
                else:
                    lines.append(
                        f"| {r.test_case.id} | {orig} | {pre} | "
                        f"{r.audio_duration_s:.1f}s | {r.generation_time_s:.1f}s | "
                        f"{r.rtf:.2f} | `{r.phonemes[:50]}` |"
                    )
        else:
            lines.append(
                "| ID | Description | Text (truncated) | Duration | Gen Time | RTF | Phonemes |"
            )
            lines.append("|---|---|---|---|---|---|---|")
            for r in results:
                text_preview = (
                    r.preprocessed_text if r.test_case.preprocess else r.test_case.text
                )[:40]
                if r.error:
                    lines.append(
                        f"| {r.test_case.id} | {r.test_case.description} | "
                        f"{text_preview} | ERROR | - | - | `{r.error}` |"
                    )
                else:
                    lines.append(
                        f"| {r.test_case.id} | {r.test_case.description} | "
                        f"{text_preview} | {r.audio_duration_s:.1f}s | "
                        f"{r.generation_time_s:.1f}s | {r.rtf:.2f} | "
                        f"`{r.phonemes[:50]}` |"
                    )
        lines.append("")

    # Performance summary
    successful = [r for r in all_results if r.error is None]
    failed = [r for r in all_results if r.error is not None]

    lines.append("\n## Performance Summary\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total tests | {len(all_results)} |")
    lines.append(f"| Successful | {len(successful)} |")
    lines.append(f"| Failed | {len(failed)} |")

    if successful:
        rtfs = [r.rtf for r in successful]
        lines.append(f"| Mean RTF | {statistics.mean(rtfs):.2f} |")
        lines.append(f"| Median RTF | {statistics.median(rtfs):.2f} |")
        lines.append(f"| Min RTF | {min(rtfs):.2f} |")
        lines.append(f"| Max RTF | {max(rtfs):.2f} |")
        lines.append(
            f"| Total generation time | {sum(r.generation_time_s for r in successful):.0f}s |"
        )
        lines.append(
            f"| Total audio generated | {sum(r.audio_duration_s for r in successful):.1f}s |"
        )
        lines.append(f"| Peak RSS | {max(r.rss_mb for r in successful):.0f} MB |")
    lines.append("")

    # Errors
    if failed:
        lines.append("\n## Errors\n")
        lines.append("| ID | Error |")
        lines.append("|---|---|")
        for r in failed:
            lines.append(f"| {r.test_case.id} | {r.error} |")
        lines.append("")

    # Listening notes template
    lines.append("\n## Listening Notes\n")
    lines.append("_Fill in after listening to each audio file._\n")
    lines.append(
        "| ID | Naturalness (1-5) | Intelligibility (1-5) | Voice Similarity (1-5) | Notes |"
    )
    lines.append("|---|---|---|---|---|")
    for r in all_results:
        lines.append(f"| {r.test_case.id} | | | | |")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to: {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="CUMADRE pt-BR TTS feasibility test")
    parser.add_argument(
        "--categories",
        default="A,B,C,D,E",
        help="Comma-separated categories to run (default: A,B,C,D,E)",
    )
    parser.add_argument(
        "--ref",
        default="tmp/audio-referencia-01.wav",
        help="Primary reference audio for voice cloning",
    )
    parser.add_argument(
        "--output-dir",
        default="tmp/feasibility-results",
        help="Output directory for audio and report",
    )
    args = parser.parse_args()

    categories = [c.strip().upper() for c in args.categories.split(",")]
    ref_audio = args.ref
    ref_audio_02 = "tmp/audio-referencia-02.wav"
    output_dir = Path(args.output_dir)

    # Validate references
    if not Path(ref_audio).exists():
        print(f"ERROR: Reference audio not found: {ref_audio}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    sys_info = get_system_info()

    print("=" * 60)
    print("CUMADRE Feasibility Test")
    print("=" * 60)
    print(f"Platform: {sys_info['platform']}")
    print(f"Thread limit: {sys_info['threads_limit']}")
    print(f"Categories: {', '.join(categories)}")
    print(f"Reference audio: {ref_audio}")
    print(f"Output dir: {output_dir}")
    print()

    # Import and limit torch threads
    print("NOTE: First run may download ~200 MB of model files from HuggingFace.")
    print()

    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)

    # Load model
    print("Loading KokoClone model...")
    t0 = time.perf_counter()
    from core.cloner import KokoClone

    cloner = KokoClone()
    load_time = time.perf_counter() - t0
    load_rss = get_rss_mb()
    print(f"Model loaded in {load_time:.1f}s (RSS: {load_rss:.0f} MB)")

    # Warm-up
    print("Running warm-up inference...")
    warmup_output = output_dir / "_warmup.wav"
    t0 = time.perf_counter()
    cloner.generate("Teste de aquecimento.", "pt", ref_audio, str(warmup_output))
    warmup_time = time.perf_counter() - t0
    warmup_output.unlink(missing_ok=True)
    print(f"Warm-up done in {warmup_time:.1f}s")

    # Initialize G2P for phoneme inspection
    from misaki.espeak import EspeakG2P

    g2p = EspeakG2P(language="pt-br")

    # Run categories
    results_by_category: dict[str, list[TestResult]] = {}

    for cat_key in categories:
        test_cases = ALL_CATEGORIES.get(cat_key)
        if test_cases is None:
            print(f"\nWARNING: Unknown category '{cat_key}', skipping.")
            continue

        cat_name = test_cases[0].category if test_cases else cat_key
        print(f"\n{'=' * 60}")
        print(f"Category {cat_key}: {cat_name} ({len(test_cases)} tests)")
        print("=" * 60)

        cat_results: list[TestResult] = []
        for tc in test_cases:
            print(f"\n  [{tc.id}] {tc.description}")
            print(f"  Text: {tc.text[:60]}{'...' if len(tc.text) > 60 else ''}")

            result = run_test_case(tc, cloner, g2p, ref_audio, ref_audio_02, output_dir)
            cat_results.append(result)

            if result.error:
                print(f"  ERROR: {result.error}")
            else:
                print(
                    f"  Duration: {result.audio_duration_s:.1f}s | Gen time: {result.generation_time_s:.1f}s | RTF: {result.rtf:.2f}"
                )
                print(f"  Phonemes: {result.phonemes[:80]}")
                if result.rss_mb > 7000:
                    print(
                        f"  WARNING: RSS at {result.rss_mb:.0f} MB, approaching 8 GB limit!"
                    )

        results_by_category[cat_key] = cat_results

        # Write report incrementally
        write_report(
            output_dir, sys_info, load_time, warmup_time, load_rss, results_by_category
        )

    # Final summary
    all_results = [r for results in results_by_category.values() for r in results]
    successful = [r for r in all_results if r.error is None]
    failed = [r for r in all_results if r.error is not None]

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(
        f"Total: {len(all_results)} | Passed: {len(successful)} | Failed: {len(failed)}"
    )
    if successful:
        rtfs = [r.rtf for r in successful]
        print(
            f"RTF: mean={statistics.mean(rtfs):.2f} median={statistics.median(rtfs):.2f} min={min(rtfs):.2f} max={max(rtfs):.2f}"
        )
        print(f"Peak RSS: {max(r.rss_mb for r in successful):.0f} MB")
    print(f"\nAudio files: {output_dir}/")
    print(f"Report: {output_dir}/report.md")
    print(
        "\nListen to the audio files and fill in the Listening Notes section of the report."
    )


if __name__ == "__main__":
    main()

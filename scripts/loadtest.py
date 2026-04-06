#!/usr/bin/env python3
"""Comadre TTS load/saturation test.

Measures throughput, latency, queue behavior, and audio integrity
under increasing concurrency against a live Comadre instance.

Usage:
    uv run --group test scripts/loadtest.py \
        --url http://10.10.10.207:8000 \
        --api-key <key> \
        --scenario all
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Text corpus — realistic BR-PT chatbot messages, grouped by size
# ---------------------------------------------------------------------------

TEXTS_SHORT = [
    "Oi, tudo bem? Quero saber o horário de funcionamento.",
    "Obrigado pela informação, até mais!",
    "Pode me enviar o cardápio por favor?",
    "Qual o prazo de entrega para minha região?",
    "Bom dia! Gostaria de fazer um pedido.",
]

TEXTS_MEDIUM = [
    (
        "Olá! Estou entrando em contato porque fiz um pedido na semana passada "
        "e até agora não recebi nenhuma atualização sobre o envio. Poderia verificar "
        "o status do meu pedido para mim? O número é quatro cinco seis sete."
    ),
    (
        "Boa tarde! Gostaria de saber se vocês fazem entrega na região de Campinas. "
        "Moro no bairro Taquaral e geralmente tenho dificuldade com entregas. "
        "Se puderem confirmar, já faço o pedido agora mesmo."
    ),
    (
        "Preciso de ajuda com minha conta. Tentei trocar a senha três vezes "
        "e continua dando erro. Já limpei o cache do navegador e tentei em outro "
        "dispositivo mas o problema persiste. O que posso fazer?"
    ),
    (
        "Estou pensando em assinar o plano anual mas tenho algumas dúvidas. "
        "Quais são as formas de pagamento aceitas? Tem desconto para pagamento "
        "à vista? E posso cancelar a qualquer momento sem multa?"
    ),
    (
        "Vi no site de vocês que tem uma promoção de frete grátis para compras "
        "acima de cem reais. Isso vale para todo o Brasil ou só para algumas "
        "regiões? Quero aproveitar mas preciso ter certeza antes de finalizar."
    ),
]

TEXTS_LONG = [
    (
        "Bom dia! Estou muito insatisfeito com o atendimento que recebi"
        " ontem na loja física de vocês. Cheguei às dez horas da manhã"
        " e fiquei esperando por mais de quarenta minutos sem ser"
        " atendido. Quando finalmente consegui falar com alguém, a"
        " pessoa não soube me explicar sobre o produto que eu queria."
        " Isso é inaceitável para uma empresa do porte de vocês."
        " Gostaria de registrar uma reclamação formal e saber quais"
        " medidas serão tomadas para melhorar o atendimento."
    ),
    (
        "Olá, tudo bem? Sou cliente de vocês há mais de dois anos e"
        " sempre tive uma experiência excelente. Porém, no último mês"
        " percebi que a qualidade do serviço caiu bastante. Os prazos"
        " de entrega estão maiores, o suporte demora para responder"
        " e alguns produtos chegaram com defeito. Entendo que"
        " imprevistos acontecem, mas gostaria de saber se há algo"
        " sendo feito para resolver esses problemas. Continuo sendo"
        " fã da marca e espero que consigam retomar o padrão de"
        " qualidade anterior."
    ),
    (
        "Boa noite! Preciso de uma orientação detalhada sobre como"
        " configurar o produto que comprei. Já li o manual que veio"
        " na caixa mas achei as instruções confusas. Tentei seguir"
        " um tutorial no YouTube mas o modelo que aparece no vídeo"
        " é diferente do meu. Vocês teriam algum guia passo a passo"
        " específico para o modelo X quinhentos? Se possível,"
        " gostaria de receber por e-mail ou WhatsApp um documento"
        " com imagens explicativas. Agradeço desde já pela atenção"
        " e aguardo o retorno de vocês."
    ),
]

ALL_TEXTS = TEXTS_SHORT + TEXTS_MEDIUM + TEXTS_LONG


def pick_text(category: str, index: int) -> str:
    if category == "short":
        return TEXTS_SHORT[index % len(TEXTS_SHORT)]
    if category == "medium":
        return TEXTS_MEDIUM[index % len(TEXTS_MEDIUM)]
    if category == "long":
        return TEXTS_LONG[index % len(TEXTS_LONG)]
    return ALL_TEXTS[index % len(ALL_TEXTS)]


def text_category(text: str) -> str:
    n = len(text)
    if n < 100:
        return "short"
    if n < 300:
        return "medium"
    return "long"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RequestMetric:
    request_id: int
    timestamp: float
    text_length: int
    text_category: str
    status_code: int
    latency: float
    response_bytes: int
    audio_valid: bool
    audio_duration: float
    queue_depth: int
    error: str = ""


@dataclass
class HealthSample:
    timestamp: float
    queue_depth: int
    memory_mb: float


@dataclass
class ScenarioConfig:
    name: str
    concurrency: int
    duration_seconds: int = 0
    request_count: int = 0
    text_profile: str = "mixed"
    description: str = ""


SCENARIOS: dict[str, ScenarioConfig] = {
    "baseline": ScenarioConfig(
        name="baseline",
        concurrency=1,
        request_count=20,
        text_profile="cycle",
        description="Single-request latency across text sizes",
    ),
    "light": ScenarioConfig(
        name="light",
        concurrency=3,
        duration_seconds=180,
        text_profile="mixed",
        description="Light chatbot-realistic load",
    ),
    "moderate": ScenarioConfig(
        name="moderate",
        concurrency=10,
        duration_seconds=300,
        text_profile="mixed",
        description="Queue buildup behavior",
    ),
    "heavy": ScenarioConfig(
        name="heavy",
        concurrency=20,
        duration_seconds=300,
        text_profile="mixed",
        description="Saturation point",
    ),
    "stress": ScenarioConfig(
        name="stress",
        concurrency=50,
        duration_seconds=180,
        text_profile="mixed",
        description="Breaking point / failure modes",
    ),
    "burst": ScenarioConfig(
        name="burst",
        concurrency=30,
        request_count=30,
        text_profile="medium",
        description="Sudden spike of simultaneous requests",
    ),
}


@dataclass
class ScenarioResults:
    config: ScenarioConfig
    requests: list[RequestMetric] = field(default_factory=list)
    health: list[HealthSample] = field(default_factory=list)
    wall_time: float = 0.0


# ---------------------------------------------------------------------------
# Audio validation
# ---------------------------------------------------------------------------


async def validate_audio(
    data: bytes, output_dir: Path, request_id: int
) -> tuple[bool, float]:
    """Validate audio with ffprobe. Returns (is_valid, duration_seconds)."""
    if len(data) < 100:
        return False, 0.0

    audio_path = output_dir / f"req_{request_id:04d}.ogg"
    audio_path.write_bytes(data)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        duration = float(stdout.decode().strip())
        valid = duration > 0.1
        if valid:
            audio_path.unlink(missing_ok=True)
        return valid, duration
    except (TimeoutError, ValueError):
        return False, 0.0


# ---------------------------------------------------------------------------
# Health monitor
# ---------------------------------------------------------------------------


async def health_monitor(
    client: httpx.AsyncClient,
    base_url: str,
    samples: list[HealthSample],
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            r = await client.get(f"{base_url}/health", timeout=5)
            data = r.json()
            samples.append(
                HealthSample(
                    timestamp=time.time(),
                    queue_depth=data.get("queue_depth", -1),
                    memory_mb=data.get("memory_mb", -1),
                )
            )
        except Exception:
            pass
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=1.0)


# ---------------------------------------------------------------------------
# Shared state for live queue depth reading
# ---------------------------------------------------------------------------


@dataclass
class LiveState:
    queue_depth: int = 0
    memory_mb: float = 0.0


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


async def worker(
    worker_id: int,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    voice: str,
    config: ScenarioConfig,
    results: list[RequestMetric],
    counter: dict[str, int],
    lock: asyncio.Lock,
    stop: asyncio.Event,
    audio_dir: Path,
    live: LiveState,
) -> None:
    headers = {"Authorization": f"Bearer {api_key}"}

    while not stop.is_set():
        async with lock:
            req_id = counter["n"]
            counter["n"] += 1

        if config.request_count and req_id >= config.request_count:
            break

        if config.text_profile == "cycle":
            cycle_idx = req_id % 3
            category = ["short", "medium", "long"][cycle_idx]
            text = pick_text(category, req_id // 3)
        elif config.text_profile == "medium":
            text = pick_text("medium", req_id)
        else:
            text = pick_text("mixed", req_id)

        cat = text_category(text)
        t0 = time.time()
        status = 0
        resp_bytes = 0
        audio_ok = False
        audio_dur = 0.0
        error = ""

        try:
            r = await client.post(
                f"{base_url}/v1/audio/speech",
                headers=headers,
                json={"input": text, "voice": voice},
                timeout=130,
            )
            status = r.status_code
            resp_bytes = len(r.content)

            if status == 200:
                audio_ok, audio_dur = await validate_audio(r.content, audio_dir, req_id)
            else:
                error = r.text[:200]
        except httpx.TimeoutException:
            status = 0
            error = "timeout"
        except Exception as exc:
            status = 0
            error = str(exc)[:200]

        latency = time.time() - t0
        metric = RequestMetric(
            request_id=req_id,
            timestamp=t0,
            text_length=len(text),
            text_category=cat,
            status_code=status,
            latency=latency,
            response_bytes=resp_bytes,
            audio_valid=audio_ok,
            audio_duration=audio_dur,
            queue_depth=live.queue_depth,
            error=error,
        )
        results.append(metric)

        tag = "\033[32mOK\033[0m" if audio_ok else f"\033[31mFAIL({status})\033[0m"
        size_kb = resp_bytes / 1024
        print(
            f"  [{time.strftime('%H:%M:%S')}] "
            f"req #{req_id:<4d} | {status} | {latency:5.1f}s | {size_kb:6.1f}KB | "
            f"{tag} | queue: {live.queue_depth} | mem: {live.memory_mb:.0f}MB"
        )


# ---------------------------------------------------------------------------
# Run a single scenario
# ---------------------------------------------------------------------------


async def run_scenario(
    config: ScenarioConfig,
    base_url: str,
    api_key: str,
    voice: str,
    output_dir: Path,
) -> ScenarioResults:
    print(f"\n{'=' * 70}")
    print(f"  SCENARIO: {config.name} — {config.description}")
    print(f"  Concurrency: {config.concurrency}", end="")
    if config.duration_seconds:
        print(f" | Duration: {config.duration_seconds}s", end="")
    if config.request_count:
        print(f" | Requests: {config.request_count}", end="")
    print(f"\n{'=' * 70}")

    audio_dir = output_dir / "audio" / config.name
    audio_dir.mkdir(parents=True, exist_ok=True)

    results = ScenarioResults(config=config)
    stop = asyncio.Event()
    counter: dict[str, int] = {"n": 0}
    lock = asyncio.Lock()
    live = LiveState()

    async with httpx.AsyncClient() as client:

        async def _health_loop() -> None:
            while not stop.is_set():
                try:
                    r = await client.get(f"{base_url}/health", timeout=5)
                    data = r.json()
                    qd = data.get("queue_depth", -1)
                    mm = data.get("memory_mb", -1)
                    live.queue_depth = qd
                    live.memory_mb = mm
                    results.health.append(
                        HealthSample(
                            timestamp=time.time(),
                            queue_depth=qd,
                            memory_mb=mm,
                        )
                    )
                except Exception:
                    pass
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1.0)

        health_task = asyncio.create_task(_health_loop())

        t_start = time.time()
        workers = [
            asyncio.create_task(
                worker(
                    i,
                    client,
                    base_url,
                    api_key,
                    voice,
                    config,
                    results.requests,
                    counter,
                    lock,
                    stop,
                    audio_dir,
                    live,
                )
            )
            for i in range(config.concurrency)
        ]

        if config.duration_seconds:
            await asyncio.sleep(config.duration_seconds)
            stop.set()

        await asyncio.gather(*workers, return_exceptions=True)
        stop.set()
        await health_task

        results.wall_time = time.time() - t_start

    return results


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

REQUEST_FIELDS = [
    "request_id",
    "timestamp",
    "text_length",
    "text_category",
    "status_code",
    "latency",
    "response_bytes",
    "audio_valid",
    "audio_duration",
    "queue_depth",
    "error",
]

HEALTH_FIELDS = ["timestamp", "queue_depth", "memory_mb"]


def write_request_csv(path: Path, metrics: list[RequestMetric]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUEST_FIELDS)
        w.writeheader()
        for m in metrics:
            w.writerow(
                {
                    "request_id": m.request_id,
                    "timestamp": f"{m.timestamp:.3f}",
                    "text_length": m.text_length,
                    "text_category": m.text_category,
                    "status_code": m.status_code,
                    "latency": f"{m.latency:.3f}",
                    "response_bytes": m.response_bytes,
                    "audio_valid": m.audio_valid,
                    "audio_duration": f"{m.audio_duration:.2f}",
                    "queue_depth": m.queue_depth,
                    "error": m.error,
                }
            )


def write_health_csv(path: Path, samples: list[HealthSample]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEALTH_FIELDS)
        w.writeheader()
        for s in samples:
            w.writerow(
                {
                    "timestamp": f"{s.timestamp:.3f}",
                    "queue_depth": s.queue_depth,
                    "memory_mb": f"{s.memory_mb:.0f}",
                }
            )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    k = (len(data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(data):
        return data[-1]
    return data[f] + (k - f) * (data[c] - data[f])


def summarize(res: ScenarioResults) -> str:
    cfg = res.config
    total = len(res.requests)
    if total == 0:
        return f"## Scenario: {cfg.name}\nNo requests completed.\n"

    ok = [m for m in res.requests if m.status_code == 200]
    failed = total - len(ok)
    ok_rate = len(ok) / total * 100 if total else 0
    throughput = total / res.wall_time * 60 if res.wall_time else 0

    latencies = sorted(m.latency for m in res.requests)
    ok_latencies = sorted(m.latency for m in ok)

    qd = [s.queue_depth for s in res.health if s.queue_depth >= 0]
    mem = [s.memory_mb for s in res.health if s.memory_mb > 0]

    valid_audio = sum(1 for m in ok if m.audio_valid)
    invalid_audio = len(ok) - valid_audio

    lines = [
        f"## Scenario: {cfg.name} (concurrency={cfg.concurrency}",
    ]
    if cfg.duration_seconds:
        lines[0] += f", duration={cfg.duration_seconds}s)"
    elif cfg.request_count:
        lines[0] += f", requests={cfg.request_count})"
    else:
        lines[0] += ")"

    lines.append(f"  {cfg.description}")
    lines.append("")
    lines.append(f"  Wall time:       {res.wall_time:8.1f}s")
    lines.append(f"  Requests total:  {total:8d}")
    lines.append(f"  Succeeded:       {len(ok):8d} ({ok_rate:.1f}%)")
    lines.append(f"  Failed:          {failed:8d} ({100 - ok_rate:.1f}%)")
    lines.append(f"  Throughput:      {throughput:8.1f} req/min")
    lines.append("")
    lines.append("  Latency (all requests):")
    lines.append(f"    p50:  {percentile(latencies, 50):8.2f}s")
    lines.append(f"    p95:  {percentile(latencies, 95):8.2f}s")
    lines.append(f"    p99:  {percentile(latencies, 99):8.2f}s")
    lines.append(f"    max:  {max(latencies):8.2f}s")
    if ok_latencies:
        lines.append("  Latency (200 OK only):")
        lines.append(f"    p50:  {percentile(ok_latencies, 50):8.2f}s")
        lines.append(f"    p95:  {percentile(ok_latencies, 95):8.2f}s")
        lines.append(f"    max:  {max(ok_latencies):8.2f}s")
    lines.append("")
    if qd:
        lines.append(f"  Queue depth:     avg={statistics.mean(qd):.1f}  max={max(qd)}")
    if mem:
        lines.append(
            f"  Memory (MB):     start={mem[0]:.0f}"
            f"  peak={max(mem):.0f}  end={mem[-1]:.0f}"
        )
    lines.append("")
    lines.append(f"  Audio valid:     {valid_audio}/{len(ok)}")
    if invalid_audio:
        lines.append(f"  Audio CORRUPT:   {invalid_audio} (check audio/ dir)")
    lines.append("")

    if failed:
        error_counts: dict[str, int] = {}
        for m in res.requests:
            if m.status_code != 200:
                key = (
                    f"{m.status_code}: {m.error[:80]}"
                    if m.error
                    else str(m.status_code)
                )
                error_counts[key] = error_counts.get(key, 0) + 1
        lines.append("  Errors:")
        for err, cnt in sorted(error_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {cnt:4d}x  {err}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Comadre TTS load test")
    parser.add_argument(
        "--url", required=True, help="Base URL (e.g. http://10.10.10.207:8000)"
    )
    parser.add_argument(
        "--api-key", required=True, help="API key for Authorization header"
    )
    parser.add_argument("--voice", default="kokoro/pm_santa", help="Voice to use")
    parser.add_argument(
        "--scenario",
        default="all",
        help="Scenario to run: " + ", ".join(["all", *SCENARIOS]),
    )
    parser.add_argument("--output", default="results", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if (
        subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True,
        ).returncode
        != 0
    ):
        print("ERROR: ffprobe not found. Install ffmpeg first.", file=sys.stderr)
        sys.exit(1)

    if args.scenario == "all":
        to_run = list(SCENARIOS.values())
    else:
        names = [s.strip() for s in args.scenario.split(",")]
        to_run = []
        for n in names:
            if n not in SCENARIOS:
                print(
                    f"ERROR: Unknown scenario '{n}'. Options: {', '.join(SCENARIOS)}",
                    file=sys.stderr,
                )
                sys.exit(1)
            to_run.append(SCENARIOS[n])

    print(f"Comadre Load Test — {args.url}")
    print(f"Voice: {args.voice}")
    print(f"Scenarios: {', '.join(s.name for s in to_run)}")
    print(f"Output: {output_dir.resolve()}")

    # Quick connectivity check
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{args.url}/health", timeout=10)
            health = r.json()
            status = health.get("status")
            version = health.get("version")
            print(f"Server status: {status} | version: {version}")
            print(f"Voices: {', '.join(health.get('voices', []))}")
        except Exception as exc:
            print(f"ERROR: Cannot reach {args.url}/health — {exc}", file=sys.stderr)
            sys.exit(1)

    all_summaries: list[str] = []

    for scenario_cfg in to_run:
        res = await run_scenario(
            scenario_cfg, args.url, args.api_key, args.voice, output_dir
        )

        write_request_csv(
            output_dir / f"{scenario_cfg.name}_requests.csv", res.requests
        )
        write_health_csv(output_dir / f"{scenario_cfg.name}_health.csv", res.health)

        summary = summarize(res)
        all_summaries.append(summary)
        print(f"\n{summary}")

    full_report = "# Comadre Load Test Results\n\n"
    full_report += f"- URL: {args.url}\n"
    full_report += f"- Voice: {args.voice}\n"
    full_report += f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    full_report += "\n".join(all_summaries)

    summary_path = output_dir / "summary.md"
    summary_path.write_text(full_report)
    print(f"\n{'=' * 70}")
    print(f"  Full report saved to: {summary_path.resolve()}")
    print(f"  CSV data in: {output_dir.resolve()}/")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""Comadre capacity test — rate-based throughput measurement.

Sends requests at controlled rates (audios/min) and measures actual
response times without timeouts. Produces a WhatsApp usage report
with ElevenLabs cost comparison.

Usage:
    uv run --group test scripts/capacity_test.py \
        --url https://YOUR_VPS_DOMAIN \
        --api-key <key> \
        --output results-capacity
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Text corpus — BR-PT chatbot messages producing 5-12s audio
# Calibrated from baseline: ~60 chars → ~5s, ~200 chars → ~12s
# Topics intentionally varied (orders, shipping, payment methods, returns,
# scheduling, complaints, fidelity, NF-e) so adjacent random picks are
# unlikely to share vocabulary or theme.
# ---------------------------------------------------------------------------

TEXTS = [
    # ~5-6s audio (55-75 chars) — short queries
    "Oi! Qual o horário de funcionamento da loja de vocês hoje?",
    "Obrigado pela ajuda! Vou seguir as instruções que você passou.",
    "Pode me informar o valor do frete para o CEP três cinco quatro?",
    "Quero cancelar meu pedido número sete oito nove dois cinco.",
    "Boa tarde! Vocês aceitam pagamento por Pix? Qual a chave?",
    "Como faço pra rastrear minha encomenda pelo site de vocês?",
    "Olá, tudo bem? Vocês têm alguma loja física em Belo Horizonte?",
    "Tem algum cupom de desconto disponível para clientes novos?",
    # ~8-10s audio (130-150 chars) — medium queries
    (
        "Olá! Fiz um pedido na semana passada e ainda não recebi."
        " Poderia verificar o status do meu pedido? O número é"
        " quatro cinco seis sete."
    ),
    (
        "Boa tarde! Gostaria de saber se vocês fazem entrega na"
        " região de Campinas. Moro no bairro Taquaral e"
        " geralmente tenho dificuldade."
    ),
    (
        "Preciso de ajuda com minha conta. Tentei trocar a senha"
        " três vezes e continua dando erro. Já limpei o cache"
        " do navegador."
    ),
    (
        "Estou pensando em assinar o plano anual mas tenho"
        " algumas dúvidas. Quais são as formas de pagamento"
        " aceitas? Tem desconto à vista?"
    ),
    (
        "Recebi o produto hoje e percebi que veio um item a menos"
        " do que tinha pedido. Como faço para resolver isso?"
        " Tenho o comprovante do pedido."
    ),
    (
        "Boa noite! Comprei pelo site mas não consigo gerar o"
        " boleto na hora do pagamento. Aparece uma mensagem de"
        " erro estranha. Já tentei várias vezes."
    ),
    (
        "Olá! Gostaria de marcar uma visita técnica para a"
        " semana que vem. É possível agendar para terça ou"
        " quarta de manhã, no bairro Pinheiros?"
    ),
    (
        "Bom dia! Sou autônomo e preciso de uma nota fiscal"
        " eletrônica do meu pedido. Vocês emitem direto pelo"
        " sistema ou tenho que solicitar separado?"
    ),
    # ~10-12s audio (180-200 chars) — long queries
    (
        "Vi no site de vocês que tem uma promoção de frete"
        " grátis para compras acima de cem reais. Isso vale"
        " para todo o Brasil ou só para algumas regiões?"
        " Quero aproveitar mas preciso ter certeza."
    ),
    (
        "Boa noite! Comprei um produto semana passada e ele"
        " chegou com defeito. A tela está riscada e o botão"
        " lateral não funciona. Gostaria de solicitar a troca"
        " por um novo, por favor."
    ),
    (
        "Olá, tudo bem? Sou cliente de vocês há dois anos."
        " Gostaria de saber se existe algum programa de"
        " fidelidade ou desconto para clientes antigos."
        " Compro com vocês todo mês."
    ),
    (
        "Preciso entender melhor a política de devolução."
        " Comprei um item em promoção mas não me adaptei."
        " Posso devolver mesmo sendo de promoção e como"
        " funciona o reembolso pelo cartão?"
    ),
    (
        "Estou tentando finalizar uma compra grande para"
        " minha empresa, são quase dois mil reais em produtos."
        " Vocês oferecem desconto para pagamento à vista no"
        " boleto ou emissão de nota com CNPJ?"
    ),
    (
        "Olá! Comprei dois produtos diferentes mas só recebi"
        " um deles na entrega de ontem. O entregador disse que"
        " o outro viria depois mas não deu prazo nenhum. Como"
        " faço para confirmar?"
    ),
    (
        "Bom dia! Trabalho como revendedor e gostaria de saber"
        " se vocês têm tabela de preços diferenciada para quem"
        " compra em quantidade. Faço pedidos mensais de"
        " cinquenta a cem peças."
    ),
    (
        "Boa tarde, tudo bem? Recebi um produto que não combina"
        " com a descrição do site. A cor é diferente e o tamanho"
        " parece menor que o anunciado. Posso trocar ou só me"
        " resta o reembolso?"
    ),
]

# ---------------------------------------------------------------------------
# ElevenLabs pricing (April 2026)
# ~1000 chars = 1 minute of audio
# ---------------------------------------------------------------------------

ELEVENLABS_PLANS = [
    ("Starter", 5.0, 30_000),
    ("Creator", 22.0, 100_000),
    ("Pro", 99.0, 500_000),
    ("Scale", 330.0, 2_000_000),
]

ELEVENLABS_CHARS_PER_MIN = 1000
HETZNER_CX33_EUR = 6.49
EUR_TO_USD = 1.08

# ---------------------------------------------------------------------------
# Rate tiers to test (audios per minute)
# ---------------------------------------------------------------------------

RATE_TIERS = [2, 5, 10, 20, 30, 50, 75, 100]
TIER_DURATION_S = 120
TIER_REQUESTS = 20

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RequestMetric:
    request_id: int
    tier_rate: int
    timestamp: float
    text_length: int
    status_code: int
    latency: float
    response_bytes: int
    audio_valid: bool
    audio_duration: float
    queue_depth: int
    memory_mb: float
    error: str = ""


@dataclass
class HealthSample:
    timestamp: float
    queue_depth: int
    memory_mb: float


@dataclass
class TierResult:
    target_rate: int
    requests: list[RequestMetric] = field(default_factory=list)
    health: list[HealthSample] = field(default_factory=list)
    wall_time: float = 0.0


# ---------------------------------------------------------------------------
# Audio validation
# ---------------------------------------------------------------------------


async def validate_audio(
    data: bytes, output_dir: Path, request_id: int
) -> tuple[bool, float]:
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
        return duration > 0.1, duration
    except (TimeoutError, ValueError):
        return False, 0.0


# ---------------------------------------------------------------------------
# Run a single rate tier
# ---------------------------------------------------------------------------


async def run_tier(
    target_rate: int,
    base_url: str,
    api_key: str,
    voice: str,
    output_dir: Path,
    rng: random.Random,
    *,
    insecure: bool = False,
) -> TierResult:
    interval = 60.0 / target_rate
    num_requests = max(TIER_REQUESTS, target_rate * 2)

    # Pre-compute the text sequence for this tier under the shared rng so
    # the workload is fully deterministic regardless of asyncio scheduling.
    texts_for_tier = [rng.choice(TEXTS) for _ in range(num_requests)]

    print(f"\n{'=' * 70}")
    print(
        f"  TIER: {target_rate} req/min"
        f" | interval={interval:.1f}s"
        f" | requests={num_requests}"
    )
    print(f"{'=' * 70}")

    audio_dir = output_dir / "audio" / f"rate_{target_rate}"
    audio_dir.mkdir(parents=True, exist_ok=True)

    result = TierResult(target_rate=target_rate)
    stop = asyncio.Event()
    live_qd = 0
    live_mem = 0.0
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(verify=not insecure) as client:

        async def _health_loop() -> None:
            nonlocal live_qd, live_mem
            while not stop.is_set():
                try:
                    r = await client.get(f"{base_url}/health", timeout=5)
                    data = r.json()
                    live_qd = data.get("queue_depth", -1)
                    live_mem = data.get("memory_mb", -1)
                    result.health.append(
                        HealthSample(
                            timestamp=time.time(),
                            queue_depth=live_qd,
                            memory_mb=live_mem,
                        )
                    )
                except Exception:
                    pass
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1.0)

        async def _send(req_id: int) -> None:
            text = texts_for_tier[req_id]
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
                    timeout=600,
                )
                status = r.status_code
                resp_bytes = len(r.content)
                if status == 200:
                    audio_ok, audio_dur = await validate_audio(
                        r.content, audio_dir, req_id
                    )
                else:
                    error = r.text[:200]
            except Exception as exc:
                error = str(exc)[:200]

            latency = time.time() - t0
            result.requests.append(
                RequestMetric(
                    request_id=req_id,
                    tier_rate=target_rate,
                    timestamp=t0,
                    text_length=len(text),
                    status_code=status,
                    latency=latency,
                    response_bytes=resp_bytes,
                    audio_valid=audio_ok,
                    audio_duration=audio_dur,
                    queue_depth=live_qd,
                    memory_mb=live_mem,
                    error=error,
                )
            )

            tag = "\033[32mOK\033[0m" if audio_ok else f"\033[31mFAIL({status})\033[0m"
            print(
                f"  [{time.strftime('%H:%M:%S')}] "
                f"#{req_id:<3d} | {latency:6.1f}s | "
                f"{audio_dur:4.1f}s audio | {tag} | "
                f"q:{live_qd} mem:{live_mem:.0f}MB"
            )

        health_task = asyncio.create_task(_health_loop())

        t_start = time.time()
        pending: set[asyncio.Task[None]] = set()

        for i in range(num_requests):
            scheduled_at = t_start + i * interval
            delay = scheduled_at - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

            task = asyncio.create_task(_send(i))
            pending.add(task)
            task.add_done_callback(pending.discard)

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        result.wall_time = time.time() - t_start
        stop.set()
        await health_task

    return result


# ---------------------------------------------------------------------------
# CSV + Summary
# ---------------------------------------------------------------------------

REQUEST_FIELDS = [
    "request_id",
    "tier_rate",
    "timestamp",
    "text_length",
    "status_code",
    "latency",
    "response_bytes",
    "audio_valid",
    "audio_duration",
    "queue_depth",
    "memory_mb",
    "error",
]


def write_csv(path: Path, results: list[RequestMetric]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUEST_FIELDS)
        w.writeheader()
        for m in results:
            w.writerow(
                {
                    "request_id": m.request_id,
                    "tier_rate": m.tier_rate,
                    "timestamp": f"{m.timestamp:.3f}",
                    "text_length": m.text_length,
                    "status_code": m.status_code,
                    "latency": f"{m.latency:.3f}",
                    "response_bytes": m.response_bytes,
                    "audio_valid": m.audio_valid,
                    "audio_duration": f"{m.audio_duration:.2f}",
                    "queue_depth": m.queue_depth,
                    "memory_mb": f"{m.memory_mb:.0f}",
                    "error": m.error,
                }
            )


def pct(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    k = (len(data) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (k - lo) * (data[hi] - data[lo])


def build_report(
    tiers: list[TierResult],
    url: str,
    voice: str,
    seed: int,
) -> str:
    lines: list[str] = []
    ln = lines.append

    ln("# Comadre Capacity Test Report")
    ln("")
    ln(f"- **Server:** {url}")
    ln(f"- **Voice:** {voice}")
    ln(f"- **Seed:** {seed}")
    ln(f"- **Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    ln("- **VPS:** Hetzner CX33 — 4 vCPU shared, 8 GB RAM")
    ln("")

    # --- Throughput table ---
    ln("## Throughput by Target Rate")
    ln("")
    ln("| Target | Actual | Success | p50 | p95 | Max | Queue | Mem | Audio |")
    ln("|--------|--------|---------|-----|-----|-----|-------|-----|-------|")

    for t in tiers:
        ok = [m for m in t.requests if m.status_code == 200]
        total = len(t.requests)
        actual = len(ok) / t.wall_time * 60 if t.wall_time else 0
        lats = sorted(m.latency for m in ok) if ok else [0]
        qds = [s.queue_depth for s in t.health if s.queue_depth >= 0]
        mems = [s.memory_mb for s in t.health if s.memory_mb > 0]
        max_q = max(qds) if qds else 0
        peak_mem = max(mems) if mems else 0
        valid = sum(1 for m in ok if m.audio_valid)

        ln(
            f"| {t.target_rate:>3d}/min"
            f" | {actual:>5.1f}/min"
            f" | {len(ok)}/{total}"
            f" | {pct(lats, 50):>5.1f}s"
            f" | {pct(lats, 95):>5.1f}s"
            f" | {max(lats):>5.1f}s"
            f" | {max_q:>5d}"
            f" | {peak_mem:>4.0f}MB"
            f" | {valid}/{len(ok)}"
            f" |"
        )

    # --- WhatsApp context ---
    ln("")
    ln("## WhatsApp Usage Context")
    ln("")
    ln("Typical WhatsApp chatbot audio usage (Brazilian market):")
    ln("")
    ln("| Metric | Value |")
    ln("|--------|-------|")
    ln("| Avg audio message | 5-12 seconds (80-200 chars) |")
    ln("| Avg user sends | 2-5 audio requests/hour |")
    ln("| Peak hours | 09-12h, 14-17h, 19-22h (3 windows) |")
    ln("| Peak multiplier | 3-5x avg rate |")
    ln("")

    base_ok = [m for m in tiers[0].requests if m.status_code == 200]
    base_lat = statistics.mean(m.latency for m in base_ok) if base_ok else 6.0
    base_dur = statistics.mean(m.audio_duration for m in base_ok) if base_ok else 8.0
    capacity_rpm = (
        (len(base_ok) / tiers[0].wall_time * 60) if tiers[0].wall_time else 10
    )

    ln("| Scenario | Users | req/min | 1 VPS? | Wait time |")
    ln("|----------|-------|---------|--------|-----------|")

    scenarios = [
        ("Small business", 50, 2),
        ("Medium business", 200, 5),
        ("Growing business", 500, 10),
        ("Large operation", 1000, 20),
        ("High-traffic", 2000, 40),
    ]
    for name, users, rpm in scenarios:
        ok_1vps = rpm <= capacity_rpm
        instances = max(1, -(-rpm // int(capacity_rpm)))
        tier_match = next(
            (t for t in tiers if t.target_rate >= rpm),
            tiers[-1],
        )
        ok_lats = sorted(m.latency for m in tier_match.requests if m.status_code == 200)
        wait = pct(ok_lats, 50) if ok_lats else rpm * base_lat
        check = "Yes" if ok_1vps else f"No ({instances}x)"
        ln(f"| {name} | {users:,} | {rpm} | {check} | ~{wait:.0f}s |")

    # --- Cost comparison ---
    ln("")
    ln("## Cost Comparison: Comadre vs ElevenLabs")
    ln("")

    avg_chars = int(
        statistics.mean(m.text_length for m in tiers[0].requests)
        if tiers[0].requests
        else 150
    )
    avg_audio_s = base_dur
    avg_audio_min = avg_audio_s / 60

    ln(f"Assumptions: avg message = {avg_chars} chars = {avg_audio_s:.0f}s audio")
    ln("")

    usage_levels = [
        ("Light (500 msgs/mo)", 500),
        ("Medium (2,000 msgs/mo)", 2000),
        ("Heavy (10,000 msgs/mo)", 10000),
        ("Intensive (50,000 msgs/mo)", 50000),
    ]

    ln("| Usage | Audio/mo | Comadre | ElevenLabs | Savings |")
    ln("|-------|----------|---------|------------|---------|")

    comadre_cost = HETZNER_CX33_EUR * EUR_TO_USD

    for label, msgs in usage_levels:
        total_chars = msgs * avg_chars
        audio_min = msgs * avg_audio_min

        el_plan = None
        for name, price, quota in ELEVENLABS_PLANS:
            if total_chars <= quota:
                el_plan = (name, price)
                break
        if el_plan is None:
            el_name = "Scale+"
            el_cost = 330.0 + ((total_chars - 2_000_000) / 1000 * 0.18)
        else:
            el_name, el_cost = el_plan

        saving = (1 - comadre_cost / el_cost) * 100 if el_cost > 0 else 0
        ln(
            f"| {label}"
            f" | {audio_min:,.0f} min"
            f" | ${comadre_cost:.2f}"
            f" | ${el_cost:.2f} ({el_name})"
            f" | {saving:+.0f}% |"
        )

    ln("")
    ln("### Key Takeaways")
    ln("")
    ln(
        f"- **Comadre fixed cost:** ${comadre_cost:.2f}/mo"
        f" (Hetzner CX33) — unlimited requests"
    )
    ln("- **ElevenLabs scales with usage:** cheap at low volume, expensive at scale")
    ln(
        f"- **Break-even:** Comadre is cheaper above"
        f" ~{30_000 // avg_chars} msgs/mo"
        f" (ElevenLabs Starter limit)"
    )
    ln("- **At 10k msgs/mo:** Comadre saves ~90%+ vs ElevenLabs")
    ln(
        "- **Quality trade-off:** ElevenLabs has"
        " superior voice quality; Comadre has zero"
        " latency dependency and full data privacy"
    )
    ln("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Comadre capacity test")
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL (e.g. https://YOUR_VPS_DOMAIN)",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="API key",
    )
    parser.add_argument(
        "--voice",
        default="kokoro/pm_santa",
        help="Voice to use",
    )
    parser.add_argument(
        "--output",
        default="results-capacity",
        help="Output directory",
    )
    parser.add_argument(
        "--tiers",
        default=",".join(str(r) for r in RATE_TIERS),
        help="Comma-separated target rates (req/min)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification (like curl -k)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible workload (default: 42)",
    )
    args = parser.parse_args()
    rng = random.Random(args.seed)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if subprocess.run(["ffprobe", "-version"], capture_output=True).returncode != 0:
        print(
            "ERROR: ffprobe not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    tiers = [int(x) for x in args.tiers.split(",")]

    print(f"Comadre Capacity Test — {args.url}")
    print(f"Voice: {args.voice}")
    print(f"Tiers: {tiers} req/min")
    print(f"Seed: {args.seed}")
    print(f"Output: {output_dir.resolve()}")

    async with httpx.AsyncClient(verify=not args.insecure) as client:
        try:
            r = await client.get(f"{args.url}/health", timeout=10)
            h = r.json()
            print(f"Server: {h.get('status')} | v{h.get('version')}")
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    all_results: list[TierResult] = []
    all_metrics: list[RequestMetric] = []

    for rate in tiers:
        res = await run_tier(
            rate,
            args.url,
            args.api_key,
            args.voice,
            output_dir,
            rng,
            insecure=args.insecure,
        )
        all_results.append(res)
        all_metrics.extend(res.requests)

    write_csv(output_dir / "all_requests.csv", all_metrics)

    report = build_report(all_results, args.url, args.voice, args.seed)
    report_path = output_dir / "capacity_report.md"
    report_path.write_text(report)

    print(f"\n{report}")
    print(f"\n{'=' * 70}")
    print(f"  Report: {report_path.resolve()}")
    print(f"  CSV: {output_dir.resolve()}/all_requests.csv")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
